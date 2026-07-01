from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.log_models import ConversationMessage
from app.db.models import Ticket

router = APIRouter()


@router.get("/stats")
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Aggregate metrics for the manager overview page."""
    now        = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=today_start.weekday())  # Monday

    # Distinct sessions that had at least one user message in each window
    convs_today = await db.scalar(
        select(func.count(distinct(ConversationMessage.session_id))).where(
            ConversationMessage.role == "user",
            ConversationMessage.created_at >= today_start,
        )
    )
    convs_week = await db.scalar(
        select(func.count(distinct(ConversationMessage.session_id))).where(
            ConversationMessage.role == "user",
            ConversationMessage.created_at >= week_start,
        )
    )

    # Resolution rate: % of unique users who were never escalated
    total_users = await db.scalar(
        select(func.count(distinct(Ticket.chat_id)))
    )
    escalated_users = await db.scalar(
        select(func.count(distinct(Ticket.chat_id))).where(Ticket.status == "escalated")
    )
    if total_users:
        resolution_rate = round((1 - (escalated_users or 0) / total_users) * 100, 1)
    else:
        resolution_rate = 100.0

    # Average user-message turns per session (across all time)
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

    # Open ticket count
    open_tickets = await db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.status == "open")
    )

    return {
        "conversations_today": convs_today or 0,
        "conversations_week":  convs_week  or 0,
        "resolution_rate":     resolution_rate,
        "avg_turns":           round(float(avg_turns_raw or 0), 1),
        "open_tickets":        open_tickets or 0,
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
