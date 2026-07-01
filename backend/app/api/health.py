"""
Agent health endpoints — aggregated from ConversationLog events.

All parsing happens in Python after fetching a bounded number of rows, which is
appropriate for a dev/staging dashboard. Switch to DB-side JSON aggregation if
volume grows significantly.
"""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.log_models import ConversationLog
from app.services.trace_service import EVT_TOOL_RESULT, EVT_LLM_CALL, EVT_ERROR

router = APIRouter()

_30D = timedelta(days=30)
_7D  = timedelta(days=7)


def _parse(row: ConversationLog) -> dict:
    try:
        return json.loads(row.payload)
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Tool success / failure rate
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tools")
async def tool_health(db: AsyncSession = Depends(get_db)):
    """Per-tool success rate and average duration (last 30 days, up to 5 000 rows)."""
    cutoff = datetime.utcnow() - _30D
    rows = (await db.execute(
        select(ConversationLog)
        .where(
            ConversationLog.event_type == EVT_TOOL_RESULT,
            ConversationLog.timestamp  >= cutoff,
        )
        .order_by(ConversationLog.timestamp.desc())
        .limit(5_000)
    )).scalars().all()

    stats: dict[str, dict] = {}
    for row in rows:
        p = _parse(row)
        tool = p.get("tool") or "unknown"
        ok   = bool(p.get("ok", False))
        dur  = p.get("duration_ms")

        if tool not in stats:
            stats[tool] = {"tool": tool, "total": 0, "successes": 0, "durations_ms": []}
        stats[tool]["total"] += 1
        if ok:
            stats[tool]["successes"] += 1
        if isinstance(dur, (int, float)):
            stats[tool]["durations_ms"].append(dur)

    result = []
    for s in stats.values():
        durations = s["durations_ms"]
        result.append({
            "tool":           s["tool"],
            "total":          s["total"],
            "successes":      s["successes"],
            "failures":       s["total"] - s["successes"],
            "success_rate":   round(s["successes"] / s["total"] * 100, 1) if s["total"] else 0,
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        })

    result.sort(key=lambda x: x["total"], reverse=True)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# LLM response-time percentiles
# ─────────────────────────────────────────────────────────────────────────────

def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    if not sorted_vals:
        return None
    idx = (len(sorted_vals) - 1) * pct / 100
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac)


@router.get("/llm")
async def llm_stats(db: AsyncSession = Depends(get_db)):
    """p50 / p95 LLM response times and call count (last 7 days)."""
    cutoff = datetime.utcnow() - _7D
    rows = (await db.execute(
        select(ConversationLog)
        .where(
            ConversationLog.event_type == EVT_LLM_CALL,
            ConversationLog.timestamp  >= cutoff,
        )
        .order_by(ConversationLog.timestamp.desc())
        .limit(5_000)
    )).scalars().all()

    durations = sorted(
        p["duration_ms"]
        for row in rows
        if isinstance((p := _parse(row)).get("duration_ms"), (int, float))
    )

    return {
        "total_calls": len(rows),
        "p50_ms":      _percentile(durations, 50),
        "p95_ms":      _percentile(durations, 95),
        "min_ms":      round(durations[0])  if durations else None,
        "max_ms":      round(durations[-1]) if durations else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Token usage per day
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tokens")
async def token_usage(db: AsyncSession = Depends(get_db)):
    """Total tokens consumed per calendar day (last 7 days, UTC)."""
    cutoff = datetime.utcnow() - _7D
    rows = (await db.execute(
        select(ConversationLog)
        .where(
            ConversationLog.event_type == EVT_LLM_CALL,
            ConversationLog.timestamp  >= cutoff,
        )
    )).scalars().all()

    daily: dict[str, dict] = {}
    for row in rows:
        p   = _parse(row)
        day = row.timestamp.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        daily[day]["prompt_tokens"]     += p.get("prompt_tokens",     0) or 0
        daily[day]["completion_tokens"] += p.get("completion_tokens", 0) or 0
        daily[day]["total_tokens"]      += p.get("total_tokens",      0) or 0

    # Fill in any missing days with zeros (last 7 days)
    today = datetime.utcnow().date()
    for i in range(7):
        day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    return sorted(daily.values(), key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# Error log
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/errors")
async def error_log(db: AsyncSession = Depends(get_db)):
    """Last 20 error events, newest first."""
    rows = (await db.execute(
        select(ConversationLog)
        .where(ConversationLog.event_type == EVT_ERROR)
        .order_by(ConversationLog.timestamp.desc())
        .limit(20)
    )).scalars().all()

    return [
        {
            "ts":         row.timestamp.isoformat() + "Z",
            "trace_id":   row.trace_id,
            "session_id": row.session_id,
            "user_id":    row.user_id,
            **_parse(row),
        }
        for row in rows
    ]
