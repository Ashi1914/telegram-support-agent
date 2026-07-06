from datetime import datetime

from pydantic import BaseModel, Field


class TicketResponse(BaseModel):
    id: int
    chat_id: str
    username: str | None
    message: str
    ai_response: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    session_id: str | None = None

    class Config:
        from_attributes = True


_VALID_STATUSES = {"open", "in_progress", "resolved", "escalated", "closed"}


class TicketStatusUpdate(BaseModel):
    status: str

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        return cls(status=v)

    def model_post_init(self, __context) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")


class TicketReply(BaseModel):
    message: str = Field(min_length=1, max_length=4096)
