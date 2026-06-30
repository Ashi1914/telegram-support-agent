from app.db.database import AsyncSessionLocal
from app.db.models import Ticket


async def create_ticket(user_id: str, issue_summary: str) -> dict:
    """
    Create a new support ticket and persist it to the database.
    Called by the AI agent when a customer issue needs to be tracked.
    """
    async with AsyncSessionLocal() as session:
        ticket = Ticket(
            chat_id=user_id,
            message=issue_summary,
            status="open",
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "created_at": ticket.created_at.isoformat(),
            "message": f"Ticket #{ticket.id} has been created and our team will follow up shortly.",
        }


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
