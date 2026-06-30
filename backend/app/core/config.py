import sys

from pydantic import model_validator
from pydantic_settings import BaseSettings

# Fields that must be non-empty for the server to start
_REQUIRED = ["TELEGRAM_BOT_TOKEN", "GROQ_API_KEY"]


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    WEBHOOK_URL: str = ""

    GROQ_API_KEY: str = ""

    DATABASE_URL: str = "postgresql+asyncpg://postgres:admin%40123@localhost:5432/support_agent"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Optional Langfuse tracing — leave blank to disable
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    model_config = {"env_file": ".env"}

    @model_validator(mode="after")
    def validate_required_and_warn(self) -> "Settings":
        # ── Hard failures: required vars ─────────────────────────────────────
        missing = [var for var in _REQUIRED if not getattr(self, var)]
        if missing:
            lines = "\n".join(f"    {var}" for var in missing)
            print(
                "\n"
                "╔══════════════════════════════════════════════════════╗\n"
                "║           STARTUP FAILED — CONFIG ERROR              ║\n"
                "╠══════════════════════════════════════════════════════╣\n"
                "║  The following required environment variables are    ║\n"
                "║  missing or empty:                                   ║\n"
                f"{lines}\n"
                "║                                                      ║\n"
                "║  Copy backend/.env.example → backend/.env            ║\n"
                "║  and fill in the missing values.                     ║\n"
                "╚══════════════════════════════════════════════════════╝\n",
                file=sys.stderr,
            )
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")

        # ── Soft warnings: optional but worth flagging ────────────────────────
        warnings: list[str] = []

        if not self.WEBHOOK_URL:
            warnings.append(
                "WEBHOOK_URL is not set — call POST /admin/webhook/register "
                "after setting it to connect Telegram."
            )

        if not self.TELEGRAM_WEBHOOK_SECRET:
            warnings.append(
                "TELEGRAM_WEBHOOK_SECRET is not set — anyone can POST to /webhook. "
                "Set a strong secret for production."
            )

        langfuse_keys = [self.LANGFUSE_PUBLIC_KEY, self.LANGFUSE_SECRET_KEY]
        if any(langfuse_keys) and not all(langfuse_keys):
            warnings.append(
                "Langfuse is partially configured — set BOTH "
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY, or neither."
            )

        for w in warnings:
            print(f"[CONFIG WARNING] {w}", file=sys.stderr)

        return self


settings = Settings()
