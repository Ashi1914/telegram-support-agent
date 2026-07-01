import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.log_models import ConversationLog, ConversationMessage
from app.db.models import Ticket

router = APIRouter()

_ABANDON_AFTER = timedelta(minutes=30)


@router.get("")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    """
    One row per session: user, start time, turn count, outcome, last message.
    """
    # ── Session-level aggregates ──────────────────────────────────────────────
    stats_rows = (await db.execute(
        select(
            ConversationMessage.session_id,
            ConversationMessage.user_id,
            func.min(ConversationMessage.created_at).label("started_at"),
            func.max(ConversationMessage.created_at).label("last_activity"),
            func.count(ConversationMessage.id)
                .filter(ConversationMessage.role == "user")
                .label("turns"),
        )
        .where(ConversationMessage.role != "summary")
        .group_by(ConversationMessage.session_id, ConversationMessage.user_id)
        .order_by(func.max(ConversationMessage.created_at).desc())
        .limit(100)
    )).all()

    if not stats_rows:
        return []

    session_ids = [r.session_id for r in stats_rows]
    user_ids    = list({r.user_id for r in stats_rows})

    # ── Last user message per session (window function) ───────────────────────
    rn = func.row_number().over(
        partition_by=ConversationMessage.session_id,
        order_by=ConversationMessage.id.desc(),
    ).label("rn")
    ranked = (
        select(ConversationMessage.session_id, ConversationMessage.content, rn)
        .where(
            ConversationMessage.role == "user",
            ConversationMessage.session_id.in_(session_ids),
        )
        .subquery()
    )
    last_msgs = {
        r.session_id: r.content
        for r in (await db.execute(
            select(ranked.c.session_id, ranked.c.content).where(ranked.c.rn == 1)
        )).all()
    }

    # ── Outcome per user (most severe ticket status wins) ─────────────────────
    ticket_rows = (await db.execute(
        select(Ticket.chat_id, Ticket.status)
        .where(Ticket.chat_id.in_(user_ids))
        .order_by(Ticket.created_at.desc())
    )).all()

    user_outcomes: dict[str, str] = {}
    for t in ticket_rows:
        prev = user_outcomes.get(t.chat_id)
        if t.status == "escalated":
            user_outcomes[t.chat_id] = "escalated"
        elif t.status == "resolved" and prev != "escalated":
            user_outcomes[t.chat_id] = "resolved"
        elif prev is None:
            user_outcomes[t.chat_id] = "open"

    now = datetime.utcnow()

    def _outcome(user_id: str, last_activity: datetime) -> str:
        status = user_outcomes.get(user_id, "open")
        if status == "open" and (now - last_activity) > _ABANDON_AFTER:
            return "abandoned"
        return status

    return [
        {
            "session_id":    r.session_id,
            "user_id":       r.user_id,
            "started_at":    r.started_at.isoformat() + "Z",
            "last_activity": r.last_activity.isoformat() + "Z",
            "turns":         r.turns,
            "outcome":       _outcome(r.user_id, r.last_activity),
            "last_message":  (last_msgs.get(r.session_id) or "")[:120],
        }
        for r in stats_rows
    ]


@router.get("/{session_id}")
async def get_conversation(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Full event log for one session — includes thoughts and tool calls.
    Falls back to ConversationMessage rows if trace logs are absent.
    """
    # ── Trace events (preferred: includes thoughts + tool calls) ─────────────
    log_rows = (await db.execute(
        select(ConversationLog)
        .where(ConversationLog.session_id == session_id)
        .order_by(ConversationLog.timestamp.asc())
    )).scalars().all()

    # ── Session metadata from ConversationMessage ─────────────────────────────
    meta = (await db.execute(
        select(
            ConversationMessage.user_id,
            func.min(ConversationMessage.created_at).label("started_at"),
            func.count(ConversationMessage.id)
                .filter(ConversationMessage.role == "user")
                .label("turns"),
        )
        .where(ConversationMessage.session_id == session_id)
        .group_by(ConversationMessage.user_id)
    )).first()

    if not log_rows and not meta:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # ── Build event list ──────────────────────────────────────────────────────
    events: list[dict] = []

    if log_rows:
        for row in log_rows:
            try:
                payload = json.loads(row.payload)
            except Exception:
                payload = {}
            events.append({
                "type":     row.event_type,
                "trace_id": row.trace_id,
                "payload":  payload,
                "ts":       row.timestamp.isoformat() + "Z",
            })
    else:
        # Fallback: synthesise events from stored messages
        msg_rows = (await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .where(ConversationMessage.role != "summary")
            .order_by(ConversationMessage.id.asc())
        )).scalars().all()

        for row in msg_rows:
            if row.role == "user":
                events.append({
                    "type": "message_received",
                    "trace_id": None,
                    "payload": {"text": row.content},
                    "ts": row.created_at.isoformat() + "Z",
                })
            elif row.role == "assistant":
                events.append({
                    "type": "agent_response",
                    "trace_id": None,
                    "payload": {"response": row.content},
                    "ts": row.created_at.isoformat() + "Z",
                })

    user_id    = meta.user_id    if meta else (log_rows[0].user_id if log_rows else "unknown")
    started_at = meta.started_at if meta else None
    turns      = meta.turns      if meta else 0

    return {
        "session_id": session_id,
        "user_id":    user_id,
        "started_at": started_at.isoformat() + "Z" if started_at else None,
        "turns":      turns,
        "events":     events,
    }
