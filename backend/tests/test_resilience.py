"""
Resilience acceptance tests.

AC-R1  Kill the knowledge-base service mid-conversation
         a) _run_tool catches the exception and returns an error dict
         b) generate_response still returns a graceful reply (no crash)

AC-R2  Introduce a 10-second delay in a tool
         The 5-second TOOL_TIMEOUT fires; result contains error + "timed out"

AC-R3  All conversation events appear in the database within 1 second
         log_event() commits synchronously; records are immediately queryable
"""
import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai_service import (
    _run_tool,
    generate_response,
    TOOL_TIMEOUT,
    FALLBACK_MESSAGE,
    _conversation_history,
)
from tests.helpers import llm_resp


# ── AC-R1a: _run_tool catches the exception and returns an error dict ─────────

async def test_kb_error_returns_error_dict():
    """
    When search_knowledge_base raises (e.g. ChromaDB is down), _run_tool must
    NOT propagate the exception — it must return {"error": True, ...} so the
    ReAct loop can feed the failure to the LLM as an Observation.
    """
    def dead_kb(query: str):
        raise ConnectionError("ChromaDB: connection refused")

    with (
        patch("app.services.ai_service.search_knowledge_base", new=dead_kb),
        patch("app.services.ai_service.log_event", new_callable=AsyncMock),
    ):
        result = await _run_tool(
            "search_knowledge_base",
            {"query": "TechNest Hub features"},
            user_id="kb_fail_user",
            trace_id="kb_fail_trace",
            session_id="kb_fail_session",
        )

    assert result.get("error") is True, f"Expected error=True in result: {result}"
    assert "message" in result, "Error dict must contain a 'message' key"
    assert "alternative" in result, "Error dict must contain an 'alternative' key"
    assert "chromadb" in result["message"].lower() or "search_knowledge_base" in result["message"].lower()


# ── AC-R1b: generate_response returns graceful reply when KB is dead ──────────

async def test_kb_failure_bot_responds_gracefully():
    """
    End-to-end: KB dies mid-conversation.  The agent should observe the error,
    reason about it, and return a helpful reply rather than crashing or returning
    the generic FALLBACK_MESSAGE.
    """
    _conversation_history.pop("kb_grace_session", None)

    def dead_kb(query: str):
        raise RuntimeError("Knowledge base is unavailable")

    with (
        patch("app.services.ai_service.search_knowledge_base", new=dead_kb),
        patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock) as mock_llm,
        patch("app.services.ai_service.log_event",       new_callable=AsyncMock),
    ):
        # Step 1: LLM decides to search KB
        # Step 2: After seeing the error Observation, LLM offers alternatives
        mock_llm.side_effect = [
            llm_resp(
                "Thought: Customer wants Hub feature info — I should search the FAQ.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "TechNest Hub features"}'
            ),
            llm_resp(
                "Thought: The search_knowledge_base tool returned an error. "
                "I should acknowledge this and offer an alternative path.\n"
                "Final Answer: I'm sorry, our FAQ search is temporarily unavailable. "
                "I can create a support ticket for you, or you can reach us directly "
                "at support@technest.io."
            ),
        ]

        reply = await generate_response(
            "What are the features of the TechNest Hub?",
            user_id="kb_grace_user",
            trace_id="kb_grace_trace",
            session_id="kb_grace_session",
        )

    assert reply, "Bot returned an empty reply after KB failure"
    assert reply != FALLBACK_MESSAGE, (
        "Bot fell back to the generic error message instead of a contextual response"
    )
    # The LLM's graceful reply should mention support or ticket creation
    reply_lower = reply.lower()
    assert any(word in reply_lower for word in ("sorry", "unavailable", "support", "ticket")), (
        f"Reply doesn't acknowledge the failure or offer alternatives: {reply!r}"
    )


# ── AC-R2: 10-second tool delay — 5-second timeout fires ─────────────────────

async def test_tool_timeout_fires_correctly():
    """
    A tool that sleeps for 10 seconds must be cut off by TOOL_TIMEOUT (5 s).
    We use create_ticket (an async coroutine) so asyncio.sleep is properly
    cancelled — no dangling background threads.

    Expected:
      - result["error"] is True
      - result["message"] mentions "timed out"
      - wall-clock time is TOOL_TIMEOUT ± 1 s  (proves timeout, not fast-return)
    """
    async def slow_create_ticket(user_id, issue_summary):
        await asyncio.sleep(10)      # simulates a stuck downstream service
        return {"ticket_id": 999}    # never reached

    with (
        patch("app.services.ai_service.create_ticket", new=slow_create_ticket),
        patch("app.services.ai_service.log_event", new_callable=AsyncMock),
    ):
        t0     = time.perf_counter()
        result = await _run_tool(
            "create_ticket",
            {"issue_summary": "Hub is completely offline"},
            user_id="timeout_user",
            trace_id="timeout_trace",
            session_id="timeout_session",
        )
        elapsed = time.perf_counter() - t0

    # Result must signal failure
    assert result.get("error") is True, (
        f"Expected error=True after timeout, got: {result}"
    )
    assert "timed out" in result.get("message", "").lower(), (
        f"Expected 'timed out' in message, got: {result.get('message')!r}"
    )
    assert "alternative" in result, "Timed-out result must include an alternative action"

    # Timing: must have fired at ~TOOL_TIMEOUT (not at 10 s, not instantly)
    assert elapsed < TOOL_TIMEOUT + 1.5, (
        f"Took {elapsed:.2f}s — timeout should have fired at {TOOL_TIMEOUT}s"
    )
    assert elapsed >= TOOL_TIMEOUT * 0.75, (
        f"Returned in {elapsed:.2f}s — suspiciously fast, timeout may not have fired "
        f"(expected ~{TOOL_TIMEOUT}s)"
    )


# ── AC-R3: All events in DB within 1 second ───────────────────────────────────

async def test_all_events_in_db_within_1s():
    """
    log_event() commits to PostgreSQL before returning.
    All events for a conversation turn must be queryable immediately after.
    """
    from sqlalchemy import select
    from sqlalchemy import delete as sql_delete
    from app.db.database import Base, engine, AsyncSessionLocal
    from app.db.log_models import ConversationLog
    import app.db.models      # register Ticket with Base.metadata
    import app.db.log_models  # register ConversationLog with Base.metadata

    # Ensure tables exist (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    trace_id   = str(uuid.uuid4())   # exactly 36 chars — matches VARCHAR(36)
    session_id = "ac-r3-session"
    user_id    = "ac-r3-user"

    # One representative event per type that occurs in a real conversation turn
    events = [
        ("message_received", {"text": "How do I reset my Hub?"}),
        ("thought",          {"step": 1, "thought": "I should search the FAQ."}),
        ("tool_call",        {"tool": "search_knowledge_base", "args": {"query": "Hub reset"}}),
        ("tool_result",      {"tool": "search_knowledge_base", "ok": True, "duration_ms": 45}),
        ("agent_response",   {"response": "Press and hold the reset button for 10 seconds."}),
    ]

    from app.services.trace_service import log_event

    t0 = time.perf_counter()

    for evt_type, payload in events:
        await log_event(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            event_type=evt_type,
            payload=payload,
        )

    # Query immediately — no sleep, no retry
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ConversationLog).where(ConversationLog.trace_id == trace_id)
        )).scalars().all()

    total_elapsed = time.perf_counter() - t0

    # Cleanup (best-effort — don't let cleanup failure mask a test failure)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                sql_delete(ConversationLog).where(ConversationLog.trace_id == trace_id)
            )
            await db.commit()
    except Exception:
        pass

    # Assertions
    assert len(rows) == len(events), (
        f"Expected {len(events)} DB rows, found {len(rows)}. "
        "Some events may not have committed before the query."
    )

    found_types = {r.event_type for r in rows}
    expected_types = {e[0] for e in events}
    assert found_types == expected_types, (
        f"Missing event types: {expected_types - found_types}"
    )

    assert total_elapsed < 1.0, (
        f"Write+query took {total_elapsed:.3f}s — expected < 1s. "
        "Check for slow DB connection or uncommitted transactions in log_event()."
    )
