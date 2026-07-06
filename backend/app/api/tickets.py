from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Ticket
from app.models.ticket import TicketReply, TicketResponse, TicketStatusUpdate
from app.services.conversation_service import session_id_at
from app.services.ticket_service import send_human_reply

router = APIRouter()


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    # Every incoming message is logged to the `tickets` table with an
    # ai_response attached (see webhook.py) for audit purposes — those rows
    # aren't real tickets and shouldn't clutter this page. Only rows created
    # via ticket_service.create_ticket() (escalations + agent follow-ups,
    # which never set ai_response) belong here.
    query = (
        select(Ticket)
        .where(Ticket.ai_response.is_(None))
        .order_by(Ticket.created_at.desc())
    )
    if status:
        query = query.where(Ticket.status == status)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.session_id = await session_id_at(ticket.chat_id, ticket.created_at)
    return ticket


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
async def update_ticket_status(
    ticket_id: int,
    body: TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.status = body.status
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/reply")
async def reply_to_ticket(
    ticket_id: int,
    body: TicketReply,
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    try:
        return await send_human_reply(ticket_id, body.message)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to send message to the customer.")
