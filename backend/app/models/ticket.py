from datetime import datetime

from pydantic import BaseModel


class TicketResponse(BaseModel):
    id: int
    chat_id: str
    username: str | None
    message: str
    ai_response: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TicketStatusUpdate(BaseModel):
    status: str
