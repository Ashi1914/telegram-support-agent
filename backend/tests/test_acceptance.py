"""
Acceptance tests for the Telegram Customer Support AI Agent.

AC-1  Cold-start overhead < 2 s
      The LLM is mocked so only our code's overhead is measured.
      Real end-to-end latency (including Groq API) is bounded by the
      ReAct loop structure and is typically 1-3 s per turn.

AC-2  Agent selects the correct tool for 5 distinct user inputs
      The LLM returns a pre-formed ReAct response; we assert the
      tool name that reaches _run_tool matches the expected value.

AC-3  Multi-turn context preserved across conversation turns
      After turn 1 the session history is saved.  Turn 2's LLM call
      receives that history in its messages list.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.ai_service import (
    generate_response,
    _parse_react_step,
    _conversation_history,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_resp(content: str):
    """Build a minimal mock that looks like a Groq chat completion response."""
    msg    = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    resp   = MagicMock(); resp.choices = [choice]
    return resp


def _search_result(answer: str = "Here is the FAQ answer."):
    return {"results": [{"question": "Q", "answer": answer, "score": 0.95}]}


def _ticket_result(ticket_id: int = 1):
    return {
        "ticket_id": ticket_id,
        "status": "open",
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


# ── AC-1: Cold-start overhead ─────────────────────────────────────────────────

async def test_cold_start_overhead_under_2s():
    """
    With an instantly-responding mocked LLM, our code overhead must be < 2 s.
    This guards against blocking I/O, slow imports, or unnecessary waits
    being introduced into the hot path.
    """
    with (
        patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock) as mock_llm,
        patch("app.services.ai_service._run_tool",       new_callable=AsyncMock) as mock_tool,
        patch("app.services.ai_service.log_event",       new_callable=AsyncMock),
    ):
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
            user_id="ac1_user",
            trace_id="ac1_trace",
            session_id="ac1_session",
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
    The LLM response is pre-formed so we verify the parsing+dispatch path,
    not LLM behaviour.
    """
    with (
        patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock) as mock_llm,
        patch("app.services.ai_service._run_tool",       new_callable=AsyncMock) as mock_tool,
        patch("app.services.ai_service.log_event",       new_callable=AsyncMock),
    ):
        mock_tool.return_value = case["tool_return"]
        mock_llm.side_effect   = [_llm_resp(s) for s in case["llm_steps"]]

        reply = await generate_response(
            case["user_input"],
            user_id=f"ac2_{case['label']}",
            trace_id="ac2_trace",
            session_id=f"ac2_{case['label']}_session",
        )

    # _run_tool was called with the right tool name as the first argument
    assert mock_tool.call_count >= 1, "No tool was called — agent skipped to Final Answer"
    actual_tool = mock_tool.call_args_list[0].args[0]
    assert actual_tool == case["expected_tool"], (
        f"[{case['label']}] expected tool '{case['expected_tool']}', "
        f"got '{actual_tool}'"
    )
    assert reply, "Agent returned an empty reply"


# ── AC-3: Multi-turn context preservation ─────────────────────────────────────

async def test_multi_turn_context_preserved():
    """
    Turn 2's LLM call must receive the user question and assistant reply
    from turn 1 in its messages list, enabling follow-up questions.
    """
    session_id = "ac3_multi_turn_session"
    _conversation_history.pop(session_id, None)   # start clean

    # ── Turn 1: ask about the device limit ───────────────────────────────────
    with (
        patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock) as mock_llm,
        patch("app.services.ai_service._run_tool",       new_callable=AsyncMock) as mock_tool,
        patch("app.services.ai_service.log_event",       new_callable=AsyncMock),
    ):
        mock_tool.return_value = _search_result("You can connect up to 50 devices.")
        mock_llm.side_effect = [
            _llm_resp(
                "Thought: Search FAQ for device limit.\n"
                "Action: search_knowledge_base\n"
                'Action Input: {"query": "device limit Hub"}'
            ),
            _llm_resp(
                "Thought: Got it.\n"
                "Final Answer: The TechNest Hub supports up to 50 connected devices."
            ),
        ]
        reply1 = await generate_response(
            "How many devices can I connect?",
            user_id="ac3_user",
            session_id=session_id,
        )

    assert "50" in reply1, f"Unexpected turn-1 reply: {reply1!r}"

    # ── Turn 2: follow-up that only makes sense with turn-1 context ──────────
    with (
        patch("app.services.ai_service._call_llm_react", new_callable=AsyncMock) as mock_llm2,
        patch("app.services.ai_service._run_tool",       new_callable=AsyncMock) as mock_tool2,
        patch("app.services.ai_service.log_event",       new_callable=AsyncMock),
    ):
        mock_tool2.return_value = _ticket_result(42)
        mock_llm2.side_effect = [
            _llm_resp(
                "Thought: User wants to raise a ticket about the device-limit issue.\n"
                "Action: create_ticket\n"
                'Action Input: {"issue_summary": "Need to connect more than 50 devices"}'
            ),
            _llm_resp(
                "Thought: Ticket created.\n"
                "Final Answer: I've raised ticket #42 for your device-limit concern!"
            ),
        ]
        reply2 = await generate_response(
            "That's not enough for me, please raise a ticket about it.",
            user_id="ac3_user",
            session_id=session_id,
        )

        # Capture the full messages list the LLM received on the FIRST call of turn 2
        turn2_messages = mock_llm2.call_args_list[0].args[0]

    assert "42" in reply2 or "ticket" in reply2.lower(), (
        f"Unexpected turn-2 reply: {reply2!r}"
    )

    # History from turn 1 must appear in the messages sent to the LLM in turn 2
    contents = [m.get("content", "") for m in turn2_messages]

    assert any("How many devices" in c for c in contents), (
        "Turn-1 user question missing from turn-2 context.\n"
        f"Messages passed to LLM:\n{contents}"
    )
    assert any("50" in c for c in contents), (
        "Turn-1 assistant reply (mentioning '50') missing from turn-2 context.\n"
        f"Messages passed to LLM:\n{contents}"
    )
