import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import delete as sa_delete, select

from app.db.database import AsyncSessionLocal
from app.db.log_models import ConversationMessage

logger = logging.getLogger(__name__)

_COMPRESS_TOKEN_THRESHOLD = 12_000  # estimated chars/4; compress stored history above this
_KEEP_RECENT_PAIRS = 6              # user+assistant pairs to always keep intact


async def load_history(session_id: str, n_turns: int = 10) -> list[dict]:
    """
    Return the last n_turns user/assistant pairs for this session, preceded by
    the most recent summary row (if one exists), all in chronological order.
    """
    async with AsyncSessionLocal() as session:
        # Fetch the most recent non-summary messages (newest first, then reverse)
        recent_stmt = (
            select(ConversationMessage)
            .where(
                ConversationMessage.session_id == session_id,
                ConversationMessage.role != "summary",
            )
            .order_by(ConversationMessage.id.desc())
            .limit(n_turns * 2)
        )
        result = await session.execute(recent_stmt)
        recent_rows = list(reversed(result.scalars().all()))

        messages: list[dict] = []

        if recent_rows:
            # Look for a summary row that predates the oldest recent row
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
            summary_result = await session.execute(summary_stmt)
            summary_row = summary_result.scalar_one_or_none()
            if summary_row:
                messages.append({"role": "assistant", "content": summary_row.content})

        messages.extend({"role": r.role, "content": r.content} for r in recent_rows)
        return messages


async def save_turn(session_id: str, user_msg: str, assistant_reply: str) -> None:
    """Persist one conversation turn (user + assistant messages) to the database."""
    async with AsyncSessionLocal() as session:
        session.add_all([
            ConversationMessage(session_id=session_id, role="user", content=user_msg),
            ConversationMessage(session_id=session_id, role="assistant", content=assistant_reply),
        ])
        await session.commit()


async def compress_if_needed(
    session_id: str,
    summarise_fn: Callable[[list[dict]], Awaitable[str]],
    token_threshold: int = _COMPRESS_TOKEN_THRESHOLD,
    keep_recent: int = _KEEP_RECENT_PAIRS,
) -> None:
    """
    If the total stored conversation exceeds token_threshold, summarise the
    older portion with a separate LLM call and replace those rows with a single
    summary row. The most recent `keep_recent` user/assistant pairs are always
    kept verbatim.
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.id.asc())
        )
        result = await session.execute(stmt)
        all_rows = result.scalars().all()

        total_tokens = sum(len(r.content) // 4 for r in all_rows)
        if total_tokens <= token_threshold:
            return

        # Keep the tail (most recent pairs) intact; compress everything else
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
        await session.execute(
            sa_delete(ConversationMessage).where(ConversationMessage.id.in_(ids_to_delete))
        )
        session.add(ConversationMessage(
            session_id=session_id,
            role="summary",
            content=f"[Summary of earlier conversation: {summary_text}]",
        ))
        await session.commit()

        logger.info(
            "Compressed %d rows into a summary for session %s (was ~%d est. tokens).",
            len(to_compress), session_id, total_tokens,
        )
