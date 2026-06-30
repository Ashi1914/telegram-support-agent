import asyncio
import json
import logging
import re
import time

from groq import AsyncGroq, APIError, APIConnectionError, RateLimitError

from app.core.config import settings
from app.services.knowledge_base import search_knowledge_base
from app.services.ticket_service import create_ticket, check_ticket_status
from app.services.trace_service import (
    log_event,
    EVT_THOUGHT, EVT_TOOL_CALL, EVT_TOOL_RESULT, EVT_AGENT_RESPONSE,
)

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=settings.GROQ_API_KEY)

# ── Per-session conversation history (multi-turn) ─────────────────────────────
# Keyed by session_id (= Telegram chat_id). Cleared on process restart.
# Stores only the clean user question and final assistant reply — not
# intermediate ReAct steps — so history stays compact and readable.
_conversation_history: dict[str, list[dict]] = {}
_MAX_HISTORY_TURNS = 10  # keep last N user/assistant exchanges


def _get_history(session_id: str) -> list[dict]:
    return list(_conversation_history.get(session_id, []))


def _append_to_history(session_id: str, user_msg: str, assistant_reply: str) -> None:
    history = _conversation_history.setdefault(session_id, [])
    history.append({"role": "user",      "content": user_msg})
    history.append({"role": "assistant", "content": assistant_reply})
    max_msgs = _MAX_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        _conversation_history[session_id] = history[-max_msgs:]


# ── Timeouts & retries ────────────────────────────────────────────────────────
TOOL_TIMEOUT     = 5.0    # seconds before a tool call is abandoned
LLM_TIMEOUT      = 30.0   # seconds for a single LLM call
LLM_MAX_RETRIES  = 2      # retries on rate-limit (total attempts = 3)
LLM_BACKOFF_BASE = 1.0    # seconds — doubles each retry: 1 s, 2 s
MAX_REACT_STEPS  = 6      # maximum Thought→Action→Observation iterations

# ── Token budget ──────────────────────────────────────────────────────────────
CONTEXT_BUDGET = 4000
WARN_AT_PCT    = 0.80
KEEP_RECENT    = 6

_TOOL_ALTERNATIVES = {
    "search_knowledge_base": (
        "The FAQ search is currently unavailable. "
        "Offer to create a support ticket for the customer instead."
    ),
    "create_ticket": (
        "Ticket creation failed. "
        "Apologise and ask the customer to email support@technest.io directly."
    ),
    "check_ticket_status": (
        "Could not retrieve the ticket. "
        "Ask the customer to email support@technest.io with their ticket ID."
    ),
}

FALLBACK_MESSAGE = (
    "I'm sorry, I'm having trouble processing your request right now. "
    "Please try again in a moment or reach us at support@technest.io."
)

KNOWN_TOOLS = {"search_knowledge_base", "create_ticket", "check_ticket_status"}

SYSTEM_PROMPT = """\
You are a friendly customer support agent for TechNest, a smart home technology company.

Think step-by-step. On EVERY response, follow this EXACT format:

Thought: <your reasoning — what does the customer need and what is the best next step?>
Action: <exactly one of: search_knowledge_base | create_ticket | check_ticket_status>
Action Input: <valid JSON object with the tool's required argument>

After receiving an Observation, continue:
Thought: <interpret the result — do you have enough to reply, or need another tool?>
Action: ... (if another tool step is needed)
  -OR-
Final Answer: <your complete, friendly reply to the customer>

Tool reference:
- search_knowledge_base  — Search the TechNest FAQ. Required arg: {"query": "concise question"}
- create_ticket          — Log an issue for human follow-up. Required arg: {"issue_summary": "clear description"}
- check_ticket_status    — Look up an existing ticket. Required arg: {"ticket_id": 123}

Rules:
- ALWAYS start with a Thought before acting.
- Never fabricate an Observation — wait for the system to provide it.
- If a tool result contains an "error" key, acknowledge it in the next Thought and adapt.
- Only write "Final Answer:" when you are ready to reply to the customer.
"""


# ── Token budget helpers ──────────────────────────────────────────────────────

def _estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        total += len(content) // 4
    return total


def _message_to_text(msg: dict) -> str:
    role = msg["role"]
    content = msg.get("content") or ""
    if role == "user":
        return f"Customer: {content}"
    if role == "assistant":
        return f"Agent: {content}"
    return f"{role}: {content}"


async def _summarise_history(messages: list[dict]) -> str:
    conversation_text = "\n".join(_message_to_text(m) for m in messages)
    if len(conversation_text) > 12_000:
        conversation_text = conversation_text[:12_000] + "\n[…earlier turns truncated…]"
    prompt = (
        "Summarise the following customer support conversation in 3–5 sentences. "
        "Include: the customer's issue, any actions already taken, and any ticket IDs mentioned.\n\n"
        f"{conversation_text}"
    )
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            ),
            timeout=10.0,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        logger.error("History summarisation failed: %s", exc)
        return "(earlier conversation — summary unavailable)"


async def _enforce_budget(messages: list[dict], user_id: str) -> list[dict]:
    token_count = _estimate_tokens(messages)
    budget_pct = token_count / CONTEXT_BUDGET

    if budget_pct >= WARN_AT_PCT:
        logger.warning(
            "Token budget %.0f%% (%d / %d est. tokens) for user %s",
            budget_pct * 100, token_count, CONTEXT_BUDGET, user_id,
        )

    if token_count <= CONTEXT_BUDGET:
        return messages

    summarisable = messages[1 : len(messages) - KEEP_RECENT]
    if not summarisable:
        logger.warning("Cannot summarise — not enough history; proceeding as-is.")
        return messages

    logger.info(
        "Context budget exceeded (%d est. tokens). Summarising %d messages for user %s.",
        token_count, len(summarisable), user_id,
    )
    summary_text = await _summarise_history(summarisable)
    summary_msg = {
        "role": "assistant",
        "content": f"[Summary of earlier conversation: {summary_text}]",
    }
    compressed = [messages[0], summary_msg] + messages[len(messages) - KEEP_RECENT :]
    logger.info(
        "After summarisation: %d est. tokens (was %d) for user %s.",
        _estimate_tokens(compressed), token_count, user_id,
    )
    return compressed


# ── ReAct response parser ─────────────────────────────────────────────────────

def _parse_react_step(text: str) -> dict:
    """
    Extract components from a ReAct-format LLM response.

    Returns one of:
      {"thought": str, "final_answer": str}
      {"thought": str, "action": str, "action_input": dict}
      {"thought": str, "final_answer": str}   ← fallback when format unreadable
    """
    # Thought
    thought_match = re.search(
        r"Thought:\s*(.+?)(?=\n(?:Action|Final Answer):|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    thought = thought_match.group(1).strip() if thought_match else ""

    # Final Answer — check first so "Action: none" patterns don't win
    final_match = re.search(r"Final Answer:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if final_match:
        return {"thought": thought, "final_answer": final_match.group(1).strip()}

    # Action + Action Input
    action_match = re.search(r"Action:\s*(\S+)", text, re.IGNORECASE)
    input_match  = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL | re.IGNORECASE)

    if action_match:
        action = action_match.group(1).strip().rstrip(".,;")

        # Fuzzy-correct minor typos / casing differences
        if action not in KNOWN_TOOLS:
            for known in KNOWN_TOOLS:
                if known.lower() in action.lower() or action.lower() in known.lower():
                    action = known
                    break

        try:
            action_input = json.loads(input_match.group(1)) if input_match else {}
        except json.JSONDecodeError:
            action_input = {}

        if action in KNOWN_TOOLS:
            return {"thought": thought, "action": action, "action_input": action_input}

    # Fallback: unstructured response — treat whole text as final answer
    logger.warning("ReAct format not detected; treating response as final answer.")
    return {"thought": thought, "final_answer": text.strip()}


# ── Tool execution ────────────────────────────────────────────────────────────

async def _run_tool(
    name: str,
    args: dict,
    user_id: str,
    trace_id: str,
    session_id: str,
) -> dict:
    """Execute one tool call with a hard timeout. Logs call + result. Never raises."""
    await log_event(
        trace_id=trace_id, session_id=session_id, user_id=user_id,
        event_type=EVT_TOOL_CALL,
        payload={"tool": name, "args": args},
    )

    t0 = time.monotonic()

    try:
        if name == "search_knowledge_base":
            coro = asyncio.to_thread(search_knowledge_base, args["query"])
        elif name == "create_ticket":
            coro = create_ticket(user_id=user_id, issue_summary=args["issue_summary"])
        elif name == "check_ticket_status":
            coro = check_ticket_status(ticket_id=args["ticket_id"])
        else:
            result = {"error": True, "message": f"Unknown tool '{name}'."}
            await log_event(
                trace_id=trace_id, session_id=session_id, user_id=user_id,
                event_type=EVT_TOOL_RESULT,
                payload={"tool": name, "result": result, "duration_ms": 0, "ok": False},
            )
            return result

        result = await asyncio.wait_for(coro, timeout=TOOL_TIMEOUT)

    except asyncio.TimeoutError:
        logger.error("Tool '%s' timed out after %.1fs for user %s", name, TOOL_TIMEOUT, user_id)
        result = {
            "error": True, "tool": name,
            "message": f"The {name} tool timed out after {int(TOOL_TIMEOUT)} seconds.",
            "alternative": _TOOL_ALTERNATIVES.get(name, "Contact support@technest.io."),
        }
    except Exception as exc:
        logger.error("Tool '%s' failed for user %s: %s", name, user_id, exc, exc_info=True)
        result = {
            "error": True, "tool": name,
            "message": f"The {name} tool encountered an error: {exc}",
            "alternative": _TOOL_ALTERNATIVES.get(name, "Contact support@technest.io."),
        }

    duration_ms = round((time.monotonic() - t0) * 1000)
    await log_event(
        trace_id=trace_id, session_id=session_id, user_id=user_id,
        event_type=EVT_TOOL_RESULT,
        payload={"tool": name, "result": result, "duration_ms": duration_ms, "ok": "error" not in result},
    )
    return result


# ── LLM call ─────────────────────────────────────────────────────────────────

async def _call_llm_react(messages: list[dict]) -> object:
    """
    Plain text generation — no tool definitions passed to the API.
    stop=["Observation:"] ensures the model halts before fabricating a tool result;
    we inject the real Observation ourselves.
    """
    last_exc: Exception | None = None

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(
                client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    max_tokens=1024,
                    temperature=0.1,
                    stop=["Observation:"],
                ),
                timeout=LLM_TIMEOUT,
            )
        except RateLimitError as exc:
            last_exc = exc
            if attempt < LLM_MAX_RETRIES:
                wait = LLM_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Rate limit (attempt %d/%d) — retrying in %.1fs",
                    attempt + 1, LLM_MAX_RETRIES + 1, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.warning("Rate limit: all %d retries exhausted.", LLM_MAX_RETRIES + 1)
        except (APIConnectionError, APIError) as exc:
            raise exc from None

    raise last_exc  # type: ignore[misc]


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_response(
    user_message: str,
    user_id: str = "",
    trace_id: str = "",
    session_id: str = "",
) -> str:
    """
    ReAct loop: Thought → Action → Observation → … → Final Answer.

    Previous turns for this session are prepended as conversation history so
    follow-up questions have context. Only the clean user question and final
    assistant reply are stored — not intermediate ReAct steps.
    """
    history  = _get_history(session_id) if session_id else []
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user",   "content": user_message},
    ]

    reply = FALLBACK_MESSAGE  # default if loop exhausted without a Final Answer

    for step in range(1, MAX_REACT_STEPS + 1):
        messages = await _enforce_budget(messages, user_id)

        # ── LLM call ──────────────────────────────────────────────────────────
        try:
            response = await _call_llm_react(messages)
        except RateLimitError:
            reply = (
                "I'm receiving a lot of requests right now and all retries failed. "
                "Please try again in a minute or email support@technest.io."
            )
            break
        except APIConnectionError:
            logger.error("Groq connection error for user %s", user_id)
            break
        except APIError as exc:
            logger.error("Groq API error for user %s: %s", user_id, exc, exc_info=True)
            break

        text = response.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": text})

        # ── Parse Thought / Action / Final Answer ─────────────────────────────
        parsed  = _parse_react_step(text)
        thought = parsed.get("thought", "")

        if thought:
            await log_event(
                trace_id=trace_id, session_id=session_id, user_id=user_id,
                event_type=EVT_THOUGHT,
                payload={"step": step, "thought": thought},
            )

        # ── Final Answer ──────────────────────────────────────────────────────
        if "final_answer" in parsed:
            reply = parsed["final_answer"]
            await log_event(
                trace_id=trace_id, session_id=session_id, user_id=user_id,
                event_type=EVT_AGENT_RESPONSE,
                payload={"response": reply, "react_steps": step},
            )
            break

        # ── Action → tool execution → Observation injection ───────────────────
        action       = parsed.get("action", "")
        action_input = parsed.get("action_input", {})

        logger.info(
            "ReAct step %d | thought=%r | action=%s | input=%s",
            step, thought[:100], action, action_input,
        )

        result      = await _run_tool(action, action_input, user_id, trace_id, session_id)
        observation = json.dumps(result, ensure_ascii=False)

        # Observation injected as a user turn so the model sees it as external data
        messages.append({"role": "user", "content": f"Observation: {observation}"})
    else:
        logger.error("ReAct loop hit MAX_REACT_STEPS=%d for user %s", MAX_REACT_STEPS, user_id)

    # Save clean turn to history so follow-ups have context
    if session_id:
        _append_to_history(session_id, user_message, reply)

    return reply
