"""
Structured tracing: every event in a conversation turn is logged as a JSON
record with a shared trace_id that links them together.

Primary store  : SQLite (conversation_logs table)
Secondary store: Langfuse (optional — set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY)
Stdout         : always emitted as a JSON log line for easy tailing / grep
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.log_models import ConversationLog

logger = logging.getLogger(__name__)

# ── Event-type constants ──────────────────────────────────────────────────────
EVT_MESSAGE_RECEIVED = "message_received"
EVT_THOUGHT          = "thought"
EVT_TOOL_CALL        = "tool_call"
EVT_TOOL_RESULT      = "tool_result"
EVT_AGENT_RESPONSE   = "agent_response"
EVT_LLM_CALL         = "llm_call"
EVT_ERROR            = "error"

# ── Optional Langfuse ─────────────────────────────────────────────────────────
_langfuse = None

if settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY:
    try:
        from langfuse import Langfuse  # type: ignore[import]
        _langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
        )
        logger.info("Langfuse tracing enabled.")
    except ImportError:
        logger.warning(
            "langfuse package not installed — install it with: pip install langfuse"
        )


# ── Public API ────────────────────────────────────────────────────────────────

def new_trace_id() -> str:
    """Return a fresh UUID4 string to identify one conversation turn."""
    return str(uuid.uuid4())


async def log_event(
    *,
    trace_id: str,
    session_id: str,
    user_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """
    Persist one structured event.  Never raises — logging must not crash the bot.

    Writes to:
      1. stdout  — JSON line (always)
      2. SQLite  — conversation_logs table (always)
      3. Langfuse — if credentials are configured (optional)
    """
    now = datetime.now(timezone.utc)

    record: dict[str, Any] = {
        "timestamp":  now.isoformat(),
        "trace_id":   trace_id,
        "session_id": session_id,
        "user_id":    user_id,
        "event_type": event_type,
        "payload":    payload,
    }

    # 1 ── stdout JSON ─────────────────────────────────────────────────────────
    logger.info(json.dumps(record, ensure_ascii=False))

    # 2 ── SQLite ──────────────────────────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as session:
            entry = ConversationLog(
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                payload=json.dumps(payload, ensure_ascii=False),
                timestamp=now.replace(tzinfo=None),
            )
            session.add(entry)
            await session.commit()
    except Exception as exc:
        logger.error("DB log write failed: %s", exc)

    # 3 ── Langfuse ────────────────────────────────────────────────────────────
    if _langfuse:
        try:
            # Upsert the trace (same trace_id → all events grouped in one trace)
            trace = _langfuse.trace(
                id=trace_id,
                name="support-turn",
                user_id=user_id,
                session_id=session_id,
            )

            if event_type == EVT_TOOL_CALL:
                # Open a span for each tool call; closed by the tool_result event
                trace.span(
                    name=payload.get("tool", "tool_call"),
                    input=payload,
                )
            elif event_type == EVT_AGENT_RESPONSE:
                trace.generation(
                    name="agent_response",
                    model="llama-3.1-8b-instant",
                    output=payload.get("response", ""),
                )
            else:
                trace.event(name=event_type, input=payload)

        except Exception as exc:
            logger.error("Langfuse log failed: %s", exc)
