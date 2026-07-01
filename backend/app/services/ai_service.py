import asyncio
import json
import logging
import re
import time

from groq import AsyncGroq, APIError, APIConnectionError, RateLimitError

from app.core.config import settings
from app.services.conversation_service import load_history, save_turn, compress_if_needed
from app.services.knowledge_base import search_knowledge_base
from app.services.ticket_service import create_ticket, check_ticket_status
from app.services.trace_service import (
    log_event,
    EVT_THOUGHT, EVT_TOOL_CALL, EVT_TOOL_RESULT, EVT_AGENT_RESPONSE,
)

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=settings.GROQ_API_KEY)

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

# ── Human-escalation detection ────────────────────────────────────────────────
MAX_TOOL_CALLS = 3  # escalate if the agent still can't resolve after this many tool uses

_ESCALATION_RE = re.compile(
    r"\b(speak|talk|chat|connect|transfer)\s+(to|with)\s+(a\s+)?"
    r"(human|person|agent|representative|rep|manager|supervisor)\b"
    r"|\bthis\s+is(n'?t|\s+not)\s+work(ing)?\b"
    r"|\b(this|it)\s+(isn'?t|doesn'?t|does\s+not|is\s+not)\s+(help(ing)?|work(ing)?)\b"
    r"|\bescalate\b"
    r"|\bi\s+want\s+(to\s+(talk|speak)\s+to\s+)?a?\s*(human|real\s+person|manager|supervisor)\b"
    r"|\bget\s+me\s+(a\s+)?(human|person|manager|supervisor|agent)\b",
    re.IGNORECASE,
)


def _wants_human(text: str) -> bool:
    return bool(_ESCALATION_RE.search(text))


async def _do_escalate(
    user_message: str,
    user_id: str,
    trace_id: str,
    session_id: str,
    reason: str,  # "user_requested" | "tool_limit_reached"
) -> str:
    """
    Create an escalated ticket and return the reply to send the customer.
    Ticket status is set to 'escalated' so the support dashboard can filter it.
    """
    if reason == "user_requested":
        issue_summary = f"[Human requested] {user_message[:500]}"
    else:
        issue_summary = f"[Unresolved after {MAX_TOOL_CALLS} tool attempts] {user_message[:500]}"

    try:
        ticket = await create_ticket(
            user_id=user_id,
            issue_summary=issue_summary,
            status="escalated",
        )
        ticket_id = ticket["ticket_id"]
        await log_event(
            trace_id=trace_id, session_id=session_id, user_id=user_id,
            event_type=EVT_AGENT_RESPONSE,
            payload={"escalated": True, "ticket_id": ticket_id, "reason": reason},
        )
        if reason == "user_requested":
            return (
                f"Of course! I've created support ticket #{ticket_id} for you and "
                f"a member of our team will be in touch with you shortly. "
                f"Thank you for your patience!"
            )
        return (
            f"I'm sorry I wasn't able to fully resolve your issue. "
            f"I've raised support ticket #{ticket_id} and a human agent "
            f"will follow up with you shortly. "
            f"Please keep ticket #{ticket_id} for your reference."
        )
    except Exception:
        logger.exception("Escalation ticket creation failed for user %s", user_id)
        return (
            "I wasn't able to resolve your issue and couldn't create a ticket automatically. "
            "Please contact us directly at support@technest.io for immediate assistance."
        )


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
    known_name: str | None = None,
) -> str:
    """
    ReAct loop: Thought → Action → Observation → … → Final Answer.

    Previous turns for this session are prepended as conversation history so
    follow-up questions have context. Only the clean user question and final
    assistant reply are stored — not intermediate ReAct steps.

    ``known_name`` is set when a returning user starts a new session after the
    30-minute inactivity timeout, so the agent can greet them by name.
    """
    # ── Explicit human-escalation request ────────────────────────────────────
    if _wants_human(user_message):
        reply = await _do_escalate(user_message, user_id, trace_id, session_id, "user_requested")
        if session_id:
            try:
                await save_turn(session_id, user_id, user_message, reply)
                await compress_if_needed(session_id, _summarise_history)
            except Exception:
                logger.exception("Failed to persist escalation turn for session %s", session_id)
        return reply

    history  = await load_history(session_id) if session_id else []

    system_content = SYSTEM_PROMPT
    if known_name:
        system_content += (
            f"\n\nNote: This is a returning customer whose Telegram username is "
            f"@{known_name}. They were inactive and are starting a new session. "
            f"Greet them warmly by name in your first reply."
        )

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        *history,
        {"role": "user",   "content": user_message},
    ]

    reply = FALLBACK_MESSAGE  # default if loop exhausted without a Final Answer
    tool_calls_this_turn = 0

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

        # Escalate if the agent has used MAX_TOOL_CALLS tools without resolving
        if tool_calls_this_turn >= MAX_TOOL_CALLS:
            logger.warning(
                "Tool call limit (%d) reached for user %s — escalating.", MAX_TOOL_CALLS, user_id
            )
            reply = await _do_escalate(
                user_message, user_id, trace_id, session_id, "tool_limit_reached"
            )
            break

        logger.info(
            "ReAct step %d | thought=%r | action=%s | input=%s",
            step, thought[:100], action, action_input,
        )

        result      = await _run_tool(action, action_input, user_id, trace_id, session_id)
        observation = json.dumps(result, ensure_ascii=False)
        tool_calls_this_turn += 1

        # Observation injected as a user turn so the model sees it as external data
        messages.append({"role": "user", "content": f"Observation: {observation}"})
    else:
        logger.error("ReAct loop hit MAX_REACT_STEPS=%d for user %s", MAX_REACT_STEPS, user_id)

    # Persist turn to DB so history survives restarts; compress if over threshold
    if session_id:
        try:
            await save_turn(session_id, user_id, user_message, reply)
            await compress_if_needed(session_id, _summarise_history)
        except Exception:
            logger.exception("Failed to persist conversation history for session %s", session_id)

    return reply
