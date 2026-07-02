from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import Ticket

# Statuses under which a user's conversation has been handed off to a human
# and the AI must not auto-reply.
_ACTIVE_HANDOFF_STATUSES = ("escalated", "in_progress")


async def create_ticket(
    user_id: str,
    issue_summary: str,
    status: str = "open",
) -> dict:
    """
    Create a new support ticket and persist it to the database.
    Called by the AI agent when a customer issue needs to be tracked,
    and by the escalation path (status="escalated") when the agent
    cannot resolve the issue or the customer requests a human agent.
    """
    async with AsyncSessionLocal() as session:
        ticket = Ticket(
            chat_id=user_id,
            message=issue_summary,
            status=status,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        if status == "escalated":
            msg = (
                f"Ticket #{ticket.id} has been escalated to our human support team "
                f"who will follow up with you shortly."
            )
        else:
            msg = f"Ticket #{ticket.id} has been created and our team will follow up shortly."

        return {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "created_at": ticket.created_at.isoformat(),
            "message": msg,
        }


async def send_human_reply(ticket_id: int, message: str) -> dict:
    """
    Send a manual reply from the dashboard (admin/manager) to the customer on
    Telegram, and record it in conversation history/logs so it shows up in the
    conversation timeline and is available as context if the AI resumes later.
    """
    from app.services import conversation_service, telegram_service
    from app.services.trace_service import EVT_HUMAN_REPLY, log_event, new_trace_id

    async with AsyncSessionLocal() as session:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            raise ValueError(f"Ticket #{ticket_id} was not found.")
        chat_id = ticket.chat_id

    await telegram_service.send_message(chat_id, message)

    session_id = await conversation_service.latest_session_id(chat_id)
    await conversation_service.save_message(session_id, chat_id, "assistant", message)

    await log_event(
        trace_id=new_trace_id(),
        session_id=session_id,
        user_id=chat_id,
        event_type=EVT_HUMAN_REPLY,
        payload={"ticket_id": ticket_id, "message": message},
    )

    return {"ticket_id": ticket_id, "chat_id": chat_id, "message": message}


async def has_active_escalation(chat_id: str) -> bool:
    """
    True when this user has a ticket that has been handed off to a human
    (escalated or being worked on) and hasn't been resolved/closed yet.
    While true, the AI must stay silent for this user.
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Ticket.id)
            .where(Ticket.chat_id == chat_id, Ticket.status.in_(_ACTIVE_HANDOFF_STATUSES))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def check_ticket_status(ticket_id: int) -> dict:
    """
    Retrieve the current status and details of a ticket by its ID.
    Called by the AI agent when a customer asks about an existing ticket.
    """
    async with AsyncSessionLocal() as session:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return {"error": f"Ticket #{ticket_id} was not found. Please check the ticket ID and try again."}
        return {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "issue_summary": ticket.message,
            "ai_response": ticket.ai_response,
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
        }
