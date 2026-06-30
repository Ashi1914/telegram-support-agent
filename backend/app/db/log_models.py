from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)   # one per turn
    session_id: Mapped[str] = mapped_column(String(64), index=True) # Telegram chat_id
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32))             # see EVENT_* constants
    payload: Mapped[str] = mapped_column(Text)                      # JSON blob
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
