"""
Human hand-off — once a ticket is escalated / in_progress, the AI must stay
silent for that user, and an admin can send a manual reply from the dashboard
that goes straight to the customer on Telegram.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.webhook import telegram_webhook
from app.models.telegram import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from app.services.ticket_service import has_active_escalation, send_human_reply


def _mock_session_ctx(mock_db):
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


# ── has_active_escalation ───────────────────────────────────────────────────

@pytest.mark.parametrize("ticket_id_found,expected", [(42, True), (None, False)])
async def test_has_active_escalation(ticket_id_found, expected):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ticket_id_found
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with patch("app.services.ticket_service.AsyncSessionLocal", _mock_session_ctx(mock_db)):
        assert await has_active_escalation("chat123") is expected


# ── send_human_reply ─────────────────────────────────────────────────────────

async def test_send_human_reply_sends_persists_and_logs():
    ticket = MagicMock(chat_id="chat123")
    mock_db = AsyncMock()
    mock_db.get.return_value = ticket

    with patch("app.services.ticket_service.AsyncSessionLocal", _mock_session_ctx(mock_db)), \
         patch("app.services.telegram_service.send_message", new_callable=AsyncMock) as mock_send, \
         patch("app.services.conversation_service.latest_session_id", new_callable=AsyncMock, return_value="chat123_1") as mock_latest, \
         patch("app.services.conversation_service.save_message", new_callable=AsyncMock) as mock_save, \
         patch("app.services.trace_service.log_event", new_callable=AsyncMock) as mock_log:
        result = await send_human_reply(7, "We've fixed it on our end!")

    mock_send.assert_awaited_once_with("chat123", "We've fixed it on our end!")
    mock_latest.assert_awaited_once_with("chat123")
    mock_save.assert_awaited_once_with("chat123_1", "chat123", "assistant", "We've fixed it on our end!")
    assert mock_log.await_args.kwargs["event_type"] == "human_reply"
    assert result == {"ticket_id": 7, "chat_id": "chat123", "message": "We've fixed it on our end!"}


async def test_send_human_reply_raises_for_missing_ticket():
    mock_db = AsyncMock()
    mock_db.get.return_value = None

    with patch("app.services.ticket_service.AsyncSessionLocal", _mock_session_ctx(mock_db)):
        with pytest.raises(ValueError):
            await send_human_reply(999, "hello")


# ── Webhook silencing ────────────────────────────────────────────────────────

def _update(text="Still waiting on this"):
    return TelegramUpdate(
        update_id=1,
        message=TelegramMessage(
            message_id=1,
            **{"from": TelegramUser(id=99, first_name="Ann", username="ann")},
            chat=TelegramChat(id=99, type="private"),
            text=text,
            date=0,
        ),
    )


async def test_webhook_stays_silent_when_handed_off_to_human():
    with patch("app.api.webhook.resolve_session", new_callable=AsyncMock, return_value=("99_1", False, None)), \
         patch("app.api.webhook.has_active_escalation", new_callable=AsyncMock, return_value=True), \
         patch("app.api.webhook.log_event", new_callable=AsyncMock), \
         patch("app.api.webhook.save_message", new_callable=AsyncMock) as mock_save, \
         patch("app.api.webhook.generate_response", new_callable=AsyncMock) as mock_generate, \
         patch("app.api.webhook.send_message", new_callable=AsyncMock) as mock_send:
        result = await telegram_webhook(_update(), db=AsyncMock())

    assert result == {"ok": True}
    mock_generate.assert_not_called()
    mock_send.assert_not_called()
    mock_save.assert_awaited_once_with("99_1", "99", "user", "Still waiting on this")


async def test_webhook_runs_ai_when_not_handed_off():
    with patch("app.api.webhook.resolve_session", new_callable=AsyncMock, return_value=("99_1", False, None)), \
         patch("app.api.webhook.has_active_escalation", new_callable=AsyncMock, return_value=False), \
         patch("app.api.webhook.log_event", new_callable=AsyncMock), \
         patch("app.api.webhook.generate_response", new_callable=AsyncMock, return_value="Here's the answer!") as mock_generate, \
         patch("app.api.webhook.send_message", new_callable=AsyncMock) as mock_send:
        mock_db = AsyncMock()
        result = await telegram_webhook(_update(), db=mock_db)

    assert result == {"ok": True}
    mock_generate.assert_awaited_once()
    mock_send.assert_awaited_once_with("99", "Here's the answer!")
