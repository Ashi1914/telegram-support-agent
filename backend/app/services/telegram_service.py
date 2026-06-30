import httpx

from app.core.config import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_chat_action(chat_id: str | int, action: str = "typing") -> None:
    """Send a transient chat action (e.g. 'typing'). Expires after ~5 s."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
        )


async def send_message(chat_id: str | int, text: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        r.raise_for_status()
        return r.json()


async def set_webhook(url: str, secret: str = "") -> dict:
    payload: dict = {"url": url}
    if secret:
        payload["secret_token"] = secret
    # Only receive message updates — ignore polls, inline queries, etc.
    payload["allowed_updates"] = ["message"]
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{TELEGRAM_API}/setWebhook", json=payload)
        r.raise_for_status()
        return r.json()


async def delete_webhook() -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{TELEGRAM_API}/deleteWebhook",
            json={"drop_pending_updates": True},
        )
        r.raise_for_status()
        return r.json()


async def get_webhook_info() -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{TELEGRAM_API}/getWebhookInfo")
        r.raise_for_status()
        return r.json()
