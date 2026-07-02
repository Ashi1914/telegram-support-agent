import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import delete as sa_delete, select

from app.db.database import AsyncSessionLocal
from app.db.log_models import ConversationMessage
from app.db.models import Ticket

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_MINUTES = 30
_COMPRESS_TOKEN_THRESHOLD = 12_000  # estimated chars/4; compress stored history above this
_KEEP_RECENT_PAIRS = 6              # user+assistant pairs to always keep intact


async def resolve_session(
    chat_id: str,
    username: str | None,
) -> tuple[str, bool, str | None]:
    """
    Determine the active session for a user and whether it is new.

    Returns ``(session_id, is_new_session, known_name)`` where:
    - ``session_id``    – ID to use for history load/save (``"{chat_id}_{n}"``)
    - ``is_new_session`` – True when starting fresh (first ever message or timeout)
    - ``known_name``    – Telegram username to greet a returning user by name;
                          None for brand-new users or sessions that are still active
    """
    async with AsyncSessionLocal() as db:
        # Find the most recent message from this user across all sessions
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.user_id == chat_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        latest = result.scalar_one_or_none()

        if latest is None:
            # Brand-new user — first ever session
            return f"{chat_id}_1", True, None

        current_session_id = latest.session_id
        elapsed = datetime.utcnow() - latest.created_at

        if elapsed <= timedelta(minutes=SESSION_TIMEOUT_MINUTES):
            # Session is still active — continue it
            return current_session_id, False, None

        # Session timed out — start a new one
        try:
            _, num_str = current_session_id.rsplit("_", 1)
            new_session_id = f"{chat_id}_{int(num_str) + 1}"
        except (ValueError, AttributeError):
            new_session_id = f"{chat_id}_2"

        known_name = username or await _lookup_username(db, chat_id)
        return new_session_id, True, known_name


async def _lookup_username(db, chat_id: str) -> str | None:
    """Return the most recently seen Telegram username for this chat_id."""
    stmt = (
        select(Ticket.username)
        .where(Ticket.chat_id == chat_id, Ticket.username.isnot(None))
        .order_by(Ticket.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def load_history(session_id: str, n_turns: int = 10) -> list[dict]:
    """
    Return the last n_turns user/assistant pairs for this session, preceded by
    the most recent summary row (if one exists), all in chronological order.
    """
    async with AsyncSessionLocal() as db:
        recent_stmt = (
            select(ConversationMessage)
            .where(
                ConversationMessage.session_id == session_id,
                ConversationMessage.role != "summary",
            )
            .order_by(ConversationMessage.id.desc())
            .limit(n_turns * 2)
        )
        result = await db.execute(recent_stmt)
        recent_rows = list(reversed(result.scalars().all()))

        messages: list[dict] = []

        if recent_rows:
            oldest_id = recent_rows[0].id
            summary_stmt = (
                select(ConversationMessage)
                .where(
                    ConversationMessage.session_id == session_id,
                    ConversationMessage.role == "summary",
                    ConversationMessage.id < oldest_id,
                )
                .order_by(ConversationMessage.id.desc())
                .limit(1)
            )
            summary_result = await db.execute(summary_stmt)
            summary_row = summary_result.scalar_one_or_none()
            if summary_row:
                messages.append({"role": "assistant", "content": summary_row.content})

        messages.extend({"role": r.role, "content": r.content} for r in recent_rows)
        return messages


async def latest_session_id(chat_id: str) -> str:
    """Return the most recent session_id for this user, or a fresh one if none exists."""
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ConversationMessage.session_id)
            .where(ConversationMessage.user_id == chat_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        session_id = result.scalar_one_or_none()
        return session_id or f"{chat_id}_1"


async def save_message(session_id: str, user_id: str, role: str, content: str) -> None:
    """Persist a single conversation message (no paired reply)."""
    async with AsyncSessionLocal() as db:
        db.add(ConversationMessage(user_id=user_id, session_id=session_id, role=role, content=content))
        await db.commit()


async def save_turn(
    session_id: str,
    user_id: str,
    user_msg: str,
    assistant_reply: str,
) -> None:
    """Persist one conversation turn (user + assistant messages) to the database."""
    async with AsyncSessionLocal() as db:
        db.add_all([
            ConversationMessage(
                user_id=user_id, session_id=session_id, role="user", content=user_msg
            ),
            ConversationMessage(
                user_id=user_id, session_id=session_id, role="assistant", content=assistant_reply
            ),
        ])
        await db.commit()


async def compress_if_needed(
    session_id: str,
    summarise_fn: Callable[[list[dict]], Awaitable[str]],
    token_threshold: int = _COMPRESS_TOKEN_THRESHOLD,
    keep_recent: int = _KEEP_RECENT_PAIRS,
) -> None:
    """
    If the total stored conversation exceeds token_threshold, summarise the
    older portion with a separate LLM call and replace those rows with a single
    summary row. The most recent ``keep_recent`` user/assistant pairs are always
    kept verbatim.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.id.asc())
        )
        result = await db.execute(stmt)
        all_rows = result.scalars().all()

        total_tokens = sum(len(r.content) // 4 for r in all_rows)
        if total_tokens <= token_threshold:
            return

        non_summary = [r for r in all_rows if r.role != "summary"]
        keep_ids = {r.id for r in non_summary[-(keep_recent * 2):]}
        to_compress = [r for r in all_rows if r.id not in keep_ids]

        if not to_compress:
            return

        messages = [
            {
                "role": "assistant" if r.role == "summary" else r.role,
                "content": r.content,
            }
            for r in to_compress
        ]
        summary_text = await summarise_fn(messages)

        ids_to_delete = [r.id for r in to_compress]
        await db.execute(
            sa_delete(ConversationMessage).where(ConversationMessage.id.in_(ids_to_delete))
        )
        # Carry the user_id forward from any row in the set being compressed
        user_id = to_compress[0].user_id
        db.add(ConversationMessage(
            user_id=user_id,
            session_id=session_id,
            role="summary",
            content=f"[Summary of earlier conversation: {summary_text}]",
        ))
        await db.commit()

        logger.info(
            "Compressed %d rows into a summary for session %s (was ~%d est. tokens).",
            len(to_compress), session_id, total_tokens,
        )
