from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.log_models import ConversationMessage
from app.db.models import Ticket

router = APIRouter()


@router.get("/stats")
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """
    Aggregate metrics for the manager overview page.
    Runs 3 DB round-trips instead of 6 by combining counts into single queries.
    """
    now         = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=today_start.weekday())  # Monday

    # ── 1 query: conversation sessions today + this week ─────────────────────
    # CASE returns session_id only when the row falls inside the target window,
    # else NULL. COUNT(DISTINCT NULL) = 0, so this correctly counts both
    # windows in a single pass.
    conv_row = (await db.execute(
        select(
            func.count(distinct(
                case(
                    (ConversationMessage.created_at >= today_start, ConversationMessage.session_id),
                    else_=None,
                )
            )).label("today"),
            func.count(distinct(ConversationMessage.session_id)).label("week"),
        )
        .where(
            ConversationMessage.role == "user",
            ConversationMessage.created_at >= week_start,
        )
    )).first()
    convs_today = conv_row.today or 0
    convs_week  = conv_row.week  or 0

    # ── 1 query: all ticket KPIs ──────────────────────────────────────────────
    ticket_row = (await db.execute(
        select(
            func.count(distinct(Ticket.chat_id)).label("total_users"),
            func.count(distinct(
                case(
                    (Ticket.status == "escalated", Ticket.chat_id),
                    else_=None,
                )
            )).label("escalated_users"),
            func.count(
                case((Ticket.status == "open", 1), else_=None)
            ).label("open_tickets"),
        )
    )).first()
    total_users     = ticket_row.total_users     or 0
    escalated_users = ticket_row.escalated_users or 0
    open_tickets    = ticket_row.open_tickets    or 0

    if total_users:
        resolution_rate = round((1 - escalated_users / total_users) * 100, 1)
    else:
        resolution_rate = 100.0

    # ── 1 query: avg turns per session (subquery required) ───────────────────
    session_turns = (
        select(
            ConversationMessage.session_id,
            func.count(ConversationMessage.id).label("turns"),
        )
        .where(ConversationMessage.role == "user")
        .group_by(ConversationMessage.session_id)
        .subquery()
    )
    avg_turns_raw = await db.scalar(select(func.avg(session_turns.c.turns)))

    return {
        "conversations_today": convs_today,
        "conversations_week":  convs_week,
        "resolution_rate":     resolution_rate,
        "avg_turns":           round(float(avg_turns_raw or 0), 1),
        "open_tickets":        open_tickets,
    }


@router.get("/feed")
async def dashboard_feed(db: AsyncSession = Depends(get_db)):
    """Last 10 user messages across all sessions, newest first."""
    rows = (await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.role == "user")
        .order_by(ConversationMessage.created_at.desc())
        .limit(10)
    )).scalars().all()

    return [
        {
            "user_id":    r.user_id,
            "session_id": r.session_id,
            "content":    r.content,
            "ts":         r.created_at.isoformat() + "Z",
        }
        for r in rows
    ]
