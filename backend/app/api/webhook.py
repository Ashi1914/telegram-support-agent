import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.db.models import Ticket
from app.models.telegram import TelegramUpdate
from app.services.ai_service import generate_response
from app.services.conversation_service import resolve_session
from app.services.telegram_service import send_message, send_chat_action
from app.services.trace_service import new_trace_id, log_event, EVT_MESSAGE_RECEIVED, EVT_ERROR

logger = logging.getLogger(__name__)
router = APIRouter()

_TYPING_INTERVAL = 4.0  # resend every 4 s; Telegram indicator expires after ~5 s


async def _keep_typing(chat_id: str) -> None:
    """Fire sendChatAction('typing') on a loop until cancelled."""
    while True:
        try:
            await send_chat_action(chat_id, "typing")
        except Exception:
            pass  # never let the indicator crash the main flow
        await asyncio.sleep(_TYPING_INTERVAL)

_SORRY = (
    "Sorry, something went wrong on our end. "
    "Please try again or contact us at support@technest.io."
)


@router.post("")
async def telegram_webhook(
    update: TelegramUpdate,
    db: AsyncSession = Depends(get_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if settings.TELEGRAM_WEBHOOK_SECRET and (
        x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="Invalid secret token")

    message = update.message
    if not message or not message.text:
        return {"ok": True}

    chat_id = str(message.chat.id)
    username = message.from_.username if message.from_ else None
    user_text = message.text

    # One trace_id ties every log event in this turn together
    trace_id = new_trace_id()

    # Resolve (or start) the session — resets after 30 min of inactivity
    session_id, is_new_session, known_name = await resolve_session(chat_id, username)

    # ── Log: incoming message ─────────────────────────────────────────────────
    await log_event(
        trace_id=trace_id,
        session_id=session_id,
        user_id=chat_id,
        event_type=EVT_MESSAGE_RECEIVED,
        payload={
            "text": user_text,
            "username": username,
            "message_id": message.message_id,
        },
    )

    # ── Generate AI reply (show typing indicator while processing) ───────────
    typing_task = asyncio.create_task(_keep_typing(chat_id))
    try:
        ai_reply = await generate_response(
            user_message=user_text,
            user_id=chat_id,
            trace_id=trace_id,
            session_id=session_id,
            known_name=known_name,
        )
    except Exception:
        logger.exception("generate_response crashed — trace_id=%s", trace_id)
        await log_event(
            trace_id=trace_id, session_id=session_id, user_id=chat_id,
            event_type=EVT_ERROR,
            payload={"stage": "generate_response", "fallback_sent": True},
        )
        ai_reply = _SORRY
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    # ── Persist ticket (best-effort) ──────────────────────────────────────────
    try:
        ticket = Ticket(
            chat_id=chat_id,
            username=username,
            message=user_text,
            ai_response=ai_reply,
            status="open",
        )
        db.add(ticket)
        await db.commit()
    except Exception:
        logger.exception("Ticket save failed — trace_id=%s", trace_id)

    # ── Send reply (best-effort) ──────────────────────────────────────────────
    try:
        await send_message(chat_id, ai_reply)
    except Exception:
        logger.exception("send_message failed — trace_id=%s", trace_id)

    # Always 200 — Telegram retries on non-200, causing duplicate messages
    return {"ok": True}
