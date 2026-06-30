import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import tickets, webhook
from app.core.config import settings
from app.db.database import Base, engine
import app.db.log_models  # registers ConversationLog with Base.metadata  # noqa: F401
from app.services.knowledge_base import init_knowledge_base
from app.services.telegram_service import (
    delete_webhook,
    get_webhook_info,
    set_webhook,
)

logger = logging.getLogger(__name__)


def _print_startup_banner() -> None:
    """Log a one-time summary of which features are enabled / disabled."""
    on = "✓ enabled"
    off = "✗ disabled"

    webhook_secret = on if settings.TELEGRAM_WEBHOOK_SECRET else f"{off} (set TELEGRAM_WEBHOOK_SECRET for production)"
    webhook_url = settings.WEBHOOK_URL or "(not set — call POST /admin/webhook/register after setting WEBHOOK_URL)"
    langfuse = (
        on
        if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
        else f"{off} (set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY to enable)"
    )

    banner = (
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        " Telegram Customer Support AI Agent — starting up\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Webhook URL     : {webhook_url}\n"
        f"  Webhook secret  : {webhook_secret}\n"
        f"  Langfuse tracing: {langfuse}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    logger.info(banner)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Load / seed the vector knowledge base
    init_knowledge_base()
    _print_startup_banner()
    yield
    await engine.dispose()


app = FastAPI(
    title="Telegram Customer Support AI Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhook management — call these from your terminal or Swagger UI (/docs)
# ---------------------------------------------------------------------------

@app.post("/admin/webhook/register", tags=["admin"])
async def register_webhook():
    """Register this server's URL as the Telegram webhook."""
    if not settings.WEBHOOK_URL:
        return {"ok": False, "error": "WEBHOOK_URL is not set in .env"}
    result = await set_webhook(settings.WEBHOOK_URL, settings.TELEGRAM_WEBHOOK_SECRET)
    return result


@app.delete("/admin/webhook", tags=["admin"])
async def remove_webhook():
    """Unregister the Telegram webhook and drop pending updates."""
    result = await delete_webhook()
    return result


@app.get("/admin/webhook/info", tags=["admin"])
async def webhook_info():
    """Return the current webhook status from Telegram."""
    result = await get_webhook_info()
    return result
