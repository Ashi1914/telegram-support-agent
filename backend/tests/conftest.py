# Set required env vars before any app module is imported.
# conftest.py is loaded by pytest before test-file collection, so these
# values are in place when app.core.config.Settings() runs its validation.
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_placeholder")
os.environ.setdefault("GROQ_API_KEY",        "test_groq_key_placeholder")
os.environ.setdefault("DATABASE_URL",        "postgresql+asyncpg://postgres:admin%40123@localhost:5432/support_agent")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "")
os.environ.setdefault("WEBHOOK_URL",         "")
