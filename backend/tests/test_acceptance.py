"""
Acceptance tests — Telegram Customer Support AI Agent.

AC-1  Cold-start overhead < 2 s
AC-2  Agent selects the correct tool for 5 distinct user inputs
AC-3  Multi-turn context preserved across conversation turns
AC-4  Session timeout → new session ID and returning-user greeting
AC-5  Human-escalation triggers: explicit phrase and 3-tool limit
AC-6  Conversation summary stored and injected into LLM context
"""
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_service import generate_response, _parse_react_step, _wants_human
from app.services.conversation_service import resolve_session


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _llm_resp(content: str):
    """Minimal mock of a Groq chat-completion response."""
    msg = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    resp = MagicMock(); resp.choices = [choice]
    return resp


def _search_result(answer: str = "Here is the FAQ answer."):
    return {"results": [{"question": "Q", "answer": answer, "score": 0.95}]}


def _ticket_result(ticket_id: int = 1, status: str = "open"):
    return {
        "ticket_id": ticket_id,
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "message": f"Ticket #{ticket_id} has been created.",
    }


def _status_result(ticket_id: int = 7):
    return {
        "ticket_id": ticket_id,
        "status": "resolved",
        "issue_summary": "Hub offline",
        "ai_response": "We fixed it.",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-02T00:00:00",
    }


def _mock_db_ctx(row_or_none):
    """
    Build a minimal AsyncSessionLocal mock that returns *row_or_none* from
    the first scalar_one_or_none() call.  Used to unit-test conversation_service
    functions without a real database.
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row_or_none

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=mock_cm)   # stands in for AsyncSessionLocal(...)


def _db_stack(stack: ExitStack, history: list | None = None) -> None:
    """
    Enter the four patches that suppress real DB / trace I/O in every
    generate_response test.  Call inside an active ExitStack.
    """
    stack.enter_context(patch(
        "app.services.ai_service.load_history",
        new_callable=AsyncMock,
        return_value=history or [],
    ))
    stack.enter_context(patch("app.services.ai_service.save_turn",          new_callable=AsyncMock))
    stack.enter_context(patch("app.services.ai_service.compress_if_needed", new_callable=AsyncMock))
    stack.enter_context(patch("app.services.ai_service.log_event",          new_callable=AsyncMock))


# ── AC-1: Cold-start overhead ─────────────────────────────────────────────────

async def test_cold_start_overhead_under_2s():
    """
    With an instantly-responding mocked LLM, our code overhead must be < 2 s.
    Guards against blocking I/O, slow imports, or unnecessary waits.
    """
    with ExitStack() as stack:
        mock_llm  = stack.enter_context(patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock))
        mock_tool = stack.enter_context(patch("app.services.ai_service._run_tool",       new_callable=AsyncMock))
        _db_stack(stack)

        mock_tool.return_value = _search_result("The Hub supports up to 50 devices.")
        mock_llm.side_effect = [
            _llm_resp(
                "Thought: Customer wants device info. I should search the FAQ.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "how many devices TechNest Hub"}'
            ),
            _llm_resp(
                "Thought: Found the answer in the FAQ.\n"
                "Final Answer: You can connect up to 50 devices to the TechNest Hub!"
            ),
        ]

        start = time.perf_counter()
        reply = await generate_response(
            "How many devices can I connect to my Hub?",
            user_id="ac1_user", trace_id="ac1_trace", session_id="ac1_session",
        )
        elapsed = time.perf_counter() - start

    assert "50" in reply, f"Unexpected reply: {reply!r}"
    assert elapsed < 2.0, (
        f"Cold-start overhead was {elapsed:.3f}s — expected < 2s. "
        "Check for blocking calls or unnecessary sleeps in the hot path."
    )


# ── AC-2: Tool selection for 5 distinct inputs ────────────────────────────────

_TOOL_CASES = [
    pytest.param(
        {
            "label":         "faq_device_limit",
            "user_input":    "How many devices can I connect to the TechNest Hub?",
            "expected_tool": "search_knowledge_base",
            "llm_steps": [
                "Thought: Device-count question — search the FAQ.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "how many devices TechNest Hub"}',
                "Thought: FAQ answered it.\nFinal Answer: Up to 50 devices!",
            ],
            "tool_return": _search_result("Up to 50 devices."),
        },
        id="faq_device_limit",
    ),
    pytest.param(
        {
            "label":         "faq_wifi_troubleshoot",
            "user_input":    "My TechNest Hub won't connect to my WiFi network.",
            "expected_tool": "search_knowledge_base",
            "llm_steps": [
                "Thought: WiFi issue — search KB for troubleshooting steps.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "Hub WiFi connection troubleshooting"}',
                "Thought: Got steps.\nFinal Answer: Ensure you use the 2.4 GHz band.",
            ],
            "tool_return": _search_result("Use 2.4 GHz band."),
        },
        id="faq_wifi_troubleshoot",
    ),
    pytest.param(
        {
            "label":         "faq_shipping",
            "user_input":    "How long does shipping take for TechNest products?",
            "expected_tool": "search_knowledge_base",
            "llm_steps": [
                "Thought: Shipping question — search the FAQ.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "shipping time TechNest"}',
                "Thought: Found shipping info.\nFinal Answer: 3–5 business days.",
            ],
            "tool_return": _search_result("3–5 business days."),
        },
        id="faq_shipping",
    ),
    pytest.param(
        {
            "label":         "create_ticket",
            "user_input":    "My smart lock keeps disconnecting. Please raise a support ticket.",
            "expected_tool": "create_ticket",
            "llm_steps": [
                "Thought: Customer wants a ticket for a disconnecting lock.\n"
                "Action: create_ticket\n"
                'Action Input: {"issue_summary": "Smart lock keeps disconnecting from the hub"}',
                "Thought: Ticket created.\nFinal Answer: I've raised ticket #1 for you!",
            ],
            "tool_return": _ticket_result(1),
        },
        id="create_ticket",
    ),
    pytest.param(
        {
            "label":         "check_ticket_status",
            "user_input":    "What's the status of my support ticket number 7?",
            "expected_tool": "check_ticket_status",
            "llm_steps": [
                "Thought: Customer wants to check ticket 7.\n"
                "Action: check_ticket_status\n"
                'Action Input: {"ticket_id": 7}',
                "Thought: Got ticket details.\nFinal Answer: Ticket #7 is resolved!",
            ],
            "tool_return": _status_result(7),
        },
        id="check_ticket_status",
    ),
]


@pytest.mark.parametrize("case", _TOOL_CASES)
async def test_agent_selects_correct_tool(case):
    """
    The agent must call the expected tool for each of 5 distinct user inputs.
    LLM response is pre-formed so we verify the parse+dispatch path only.
    """
    with ExitStack() as stack:
        mock_llm  = stack.enter_context(patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock))
        mock_tool = stack.enter_context(patch("app.services.ai_service._run_tool",       new_callable=AsyncMock))
        _db_stack(stack)

        mock_tool.return_value = case["tool_return"]
        mock_llm.side_effect   = [_llm_resp(s) for s in case["llm_steps"]]

        reply = await generate_response(
            case["user_input"],
            user_id=f"ac2_{case['label']}",
            trace_id="ac2_trace",
            session_id=f"ac2_{case['label']}_session",
        )

    assert mock_tool.call_count >= 1, "No tool was called — agent skipped to Final Answer"
    actual_tool = mock_tool.call_args_list[0].args[0]
    assert actual_tool == case["expected_tool"], (
        f"[{case['label']}] expected tool '{case['expected_tool']}', got '{actual_tool}'"
    )
    assert reply


# ── AC-3: Multi-turn context preservation ─────────────────────────────────────

async def test_multi_turn_context_preserved():
    """
    Turn 2's LLM call must contain the user question and AI reply from turn 1
    in its messages list, enabling follow-up questions to make sense.
    """
    turn1_user  = "How many devices can I connect?"
    turn1_reply = "The TechNest Hub supports up to 50 connected devices."

    # ── Turn 1: load empty history, generate reply ────────────────────────────
    with ExitStack() as stack:
        mock_llm1  = stack.enter_context(patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock))
        mock_tool1 = stack.enter_context(patch("app.services.ai_service._run_tool",       new_callable=AsyncMock))
        _db_stack(stack)

        mock_tool1.return_value = _search_result("Up to 50 devices.")
        mock_llm1.side_effect = [
            _llm_resp(
                "Thought: Search FAQ for device limit.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "device limit Hub"}'
            ),
            _llm_resp(f"Thought: Got it.\nFinal Answer: {turn1_reply}"),
        ]
        reply1 = await generate_response(
            turn1_user, user_id="ac3_user", session_id="ac3_session",
        )

    assert "50" in reply1, f"Unexpected turn-1 reply: {reply1!r}"

    # ── Turn 2: load_history returns turn-1 exchange; verify LLM receives it ──
    turn1_history = [
        {"role": "user",      "content": turn1_user},
        {"role": "assistant", "content": turn1_reply},
    ]

    with ExitStack() as stack:
        mock_llm2  = stack.enter_context(patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock))
        mock_tool2 = stack.enter_context(patch("app.services.ai_service._run_tool",       new_callable=AsyncMock))
        _db_stack(stack, history=turn1_history)

        mock_tool2.return_value = _ticket_result(42)
        mock_llm2.side_effect = [
            _llm_resp(
                "Thought: User wants to raise a ticket about the device-limit issue.\n"
                "Action: create_ticket\n"
                'Action Input: {"issue_summary": "Need to connect more than 50 devices"}'
            ),
            _llm_resp("Thought: Ticket created.\nFinal Answer: I've raised ticket #42!"),
        ]
        reply2 = await generate_response(
            "That's not enough for me, please raise a ticket about it.",
            user_id="ac3_user",
            session_id="ac3_session",
        )
        turn2_messages = mock_llm2.call_args_list[0].args[0]

    assert "42" in reply2 or "ticket" in reply2.lower(), (
        f"Unexpected turn-2 reply: {reply2!r}"
    )

    contents = [m.get("content", "") for m in turn2_messages]
    assert any(turn1_user in c for c in contents), (
        "Turn-1 user question missing from turn-2 context.\n"
        f"Messages passed to LLM:\n{contents}"
    )
    assert any("50" in c for c in contents), (
        "Turn-1 assistant reply (mentioning '50') missing from turn-2 context.\n"
        f"Messages passed to LLM:\n{contents}"
    )


# ── AC-4: Session timeout and returning-user greeting ─────────────────────────

async def test_session_timeout_creates_new_session_with_greeting():
    """
    When the most recent stored message is > 30 min old, resolve_session must
    return a new session_id (counter incremented), is_new=True, and known_name.
    """
    old_row = MagicMock()
    old_row.session_id = "555_2"
    old_row.created_at = datetime.utcnow() - timedelta(minutes=35)

    with patch("app.services.conversation_service.AsyncSessionLocal", _mock_db_ctx(old_row)):
        session_id, is_new, known_name = await resolve_session("555", "alice")

    assert session_id  == "555_3", f"Expected '555_3', got {session_id!r}"
    assert is_new      is True,    "Expected is_new=True after 30-min timeout"
    assert known_name  == "alice", f"Expected known_name='alice', got {known_name!r}"


async def test_active_session_continues_unchanged():
    """A message within 30 min must reuse the current session with no greeting."""
    recent_row = MagicMock()
    recent_row.session_id = "666_1"
    recent_row.created_at = datetime.utcnow() - timedelta(minutes=10)

    with patch("app.services.conversation_service.AsyncSessionLocal", _mock_db_ctx(recent_row)):
        session_id, is_new, known_name = await resolve_session("666", "bob")

    assert session_id == "666_1", f"Expected '666_1', got {session_id!r}"
    assert is_new     is False,   "Active session must not be marked as new"
    assert known_name is None,    "known_name must be None for an active session"


async def test_brand_new_user_gets_first_session():
    """No prior messages → first session, no known name, no greeting."""
    with patch("app.services.conversation_service.AsyncSessionLocal", _mock_db_ctx(None)):
        session_id, is_new, known_name = await resolve_session("777", None)

    assert session_id == "777_1", f"Expected '777_1', got {session_id!r}"
    assert is_new     is True
    assert known_name is None


async def test_returning_user_greeting_in_system_prompt():
    """
    When generate_response receives known_name (set by resolve_session on timeout),
    the system prompt the LLM sees must contain the greeting instruction.
    """
    captured: list[list[dict]] = []

    async def capture_llm(messages):
        captured.append(list(messages))
        return _llm_resp("Thought: Greet user.\nFinal Answer: Welcome back, Alice!")

    with ExitStack() as stack:
        stack.enter_context(patch("app.services.ai_service._call_llm_react", side_effect=capture_llm))
        _db_stack(stack)

        await generate_response(
            "Hello!", user_id="ac4_user", session_id="ac4_s2", known_name="alice",
        )

    assert captured, "LLM was never called"
    system_msg = next(m for m in captured[0] if m["role"] == "system")
    prompt_lower = system_msg["content"].lower()

    assert "alice" in prompt_lower, (
        f"Greeting note must include the customer's name.\nSystem: {system_msg['content']!r}"
    )
    assert "returning" in prompt_lower or "greet" in prompt_lower, (
        f"System prompt must instruct the agent to greet the returning customer.\n"
        f"System: {system_msg['content']!r}"
    )


# ── AC-5: Human-escalation triggers ───────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "I want to speak to a human",
    "Can I talk to a real person?",
    "This isn't working",
    "escalate this please",
    "get me a manager",
    "connect me with an agent",
])
def test_escalation_phrases_detected(phrase):
    """_wants_human must recognise all common escalation phrases."""
    assert _wants_human(phrase), f"Phrase not detected as escalation: {phrase!r}"


async def test_explicit_human_request_bypasses_llm_and_creates_ticket():
    """
    When the customer says 'speak to a human', the ReAct loop must be skipped
    entirely, an escalated ticket created, and the ticket ID returned to the user.
    """
    escalated_ticket = _ticket_result(77, status="escalated")
    escalated_ticket["message"] = "Ticket #77 has been escalated."

    with ExitStack() as stack:
        mock_llm    = stack.enter_context(patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock))
        mock_create = stack.enter_context(patch("app.services.ai_service.create_ticket",   new_callable=AsyncMock, return_value=escalated_ticket))
        stack.enter_context(patch("app.services.ai_service.save_turn",          new_callable=AsyncMock))
        stack.enter_context(patch("app.services.ai_service.compress_if_needed", new_callable=AsyncMock))
        stack.enter_context(patch("app.services.ai_service.log_event",          new_callable=AsyncMock))

        reply = await generate_response(
            "I want to speak to a human please",
            user_id="ac5a_user", trace_id="ac5a_trace", session_id="ac5a_session",
        )

    mock_llm.assert_not_called()   # ReAct loop must be bypassed entirely
    mock_create.assert_called_once()

    kwargs = mock_create.call_args.kwargs
    assert kwargs.get("status") == "escalated", (
        f"Ticket must have status='escalated', got {kwargs.get('status')!r}"
    )
    assert "77" in reply, f"Ticket ID must appear in reply: {reply!r}"
    assert "team" in reply.lower() or "follow" in reply.lower(), (
        f"Reply must mention human follow-up: {reply!r}"
    )


async def test_three_tool_calls_without_resolution_escalates():
    """
    When the agent makes 3 tool calls without a Final Answer, it must stop,
    create an escalated ticket, and tell the customer the ticket number.
    """
    always_action = _llm_resp(
        "Thought: Let me search again.\n"
        "Action: search_knowledge_base\n"
        'Action Input: {"query": "device issue"}'
    )
    escalated_ticket = _ticket_result(55, status="escalated")
    escalated_ticket["message"] = "Ticket #55 has been escalated."

    with ExitStack() as stack:
        stack.enter_context(patch("app.services.ai_service._call_llm_react",
                                  new_callable=AsyncMock, return_value=always_action))
        mock_tool   = stack.enter_context(patch("app.services.ai_service._run_tool",
                                                new_callable=AsyncMock, return_value={"error": "KB unavailable"}))
        mock_create = stack.enter_context(patch("app.services.ai_service.create_ticket",
                                                new_callable=AsyncMock, return_value=escalated_ticket))
        _db_stack(stack)

        reply = await generate_response(
            "My device keeps crashing and nothing helps.",
            user_id="ac5b_user", trace_id="ac5b_trace", session_id="ac5b_session",
        )

    # Exactly 3 tool calls before escalation
    assert mock_tool.call_count == 3, (
        f"Expected exactly 3 tool calls before escalating, got {mock_tool.call_count}"
    )

    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs.get("status") == "escalated", (
        f"Expected status='escalated', got {kwargs.get('status')!r}"
    )
    assert "[Unresolved" in kwargs.get("issue_summary", ""), (
        f"issue_summary must describe unresolved state: {kwargs.get('issue_summary')!r}"
    )
    assert "55" in reply, f"Ticket ID must appear in escalation reply: {reply!r}"
    assert "human" in reply.lower() or "agent" in reply.lower() or "follow up" in reply.lower(), (
        f"Reply must mention human follow-up: {reply!r}"
    )


# ── AC-6: Conversation summary ────────────────────────────────────────────────

async def test_summary_row_is_included_in_llm_context():
    """
    When load_history returns a summary row (from a previous compression run),
    its content must appear in the messages the LLM receives — so the agent
    has full context even though the raw history was compacted.
    """
    summary_content = (
        "[Summary of earlier conversation: Customer reported Hub connectivity "
        "issues. A factory reset was performed and the problem was resolved. "
        "Ticket #12 was created and later closed.]"
    )
    history_with_summary = [
        {"role": "assistant", "content": summary_content},       # summary row
        {"role": "user",      "content": "Can I connect more sensors now?"},
        {"role": "assistant", "content": "Yes, the Hub supports up to 50 sensors."},
    ]

    captured: list[list[dict]] = []

    async def capture_llm(messages):
        captured.append(list(messages))
        return _llm_resp("Thought: Follow-up on warranty.\nFinal Answer: Yes, 2-year warranty.")

    with ExitStack() as stack:
        stack.enter_context(patch("app.services.ai_service._call_llm_react", side_effect=capture_llm))
        _db_stack(stack, history=history_with_summary)

        await generate_response(
            "Does the warranty cover the sensors too?",
            user_id="ac6_user",
            session_id="ac6_session",
        )

    assert captured, "LLM was never called"
    contents = [m["content"] for m in captured[0]]

    assert any(summary_content in c for c in contents), (
        "Summary row was not forwarded to the LLM.\n"
        f"Messages LLM received:\n{contents}"
    )
    assert any("Can I connect more sensors" in c for c in contents), (
        "Recent history messages after the summary must also be in LLM context"
    )


async def test_compress_if_needed_is_called_after_every_turn():
    """
    compress_if_needed must be awaited after each successful turn so that the
    DB compression threshold is evaluated and old rows are summarised when needed.
    """
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.services.ai_service._call_llm_react",
            new_callable=AsyncMock,
            return_value=_llm_resp("Thought: Simple answer.\nFinal Answer: Here you go!"),
        ))
        stack.enter_context(patch("app.services.ai_service.load_history", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("app.services.ai_service.save_turn",    new_callable=AsyncMock))
        mock_compress = stack.enter_context(patch("app.services.ai_service.compress_if_needed", new_callable=AsyncMock))
        stack.enter_context(patch("app.services.ai_service.log_event",    new_callable=AsyncMock))

        await generate_response("Quick question!", user_id="ac6b_user", session_id="ac6b_session")

    assert mock_compress.await_count == 1, (
        f"compress_if_needed must be awaited once per turn, "
        f"was awaited {mock_compress.await_count} time(s)"
    )
