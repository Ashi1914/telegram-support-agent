import { useEffect, useState } from "react";
import {
  fetchHealthTools,
  fetchHealthLlm,
  fetchHealthTokens,
  fetchHealthErrors,
} from "../services/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function msLabel(ms) {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function fmt(isoStr) {
  if (!isoStr) return "—";
  return new Date(isoStr).toLocaleString([], {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function shortDate(dateStr) {
  // "2025-07-01" → "Jul 1"
  const d = new Date(dateStr + "T12:00:00Z");
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

// ── Sub-panels ────────────────────────────────────────────────────────────────

function ToolHealthPanel({ data }) {
  if (!data) return <p className="dash-loading">Loading…</p>;
  if (data.length === 0) return <p className="health-empty">No tool calls recorded yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Tool</th>
          <th>Total calls</th>
          <th>Success rate</th>
          <th>Failures</th>
          <th>Avg duration</th>
        </tr>
      </thead>
      <tbody>
        {data.map((row) => (
          <tr key={row.tool}>
            <td className="health-tool-name">{row.tool}</td>
            <td>{row.total}</td>
            <td>
              <div className="rate-bar-wrap">
                <div
                  className="rate-bar"
                  style={{
                    width: `${row.success_rate}%`,
                    background: row.success_rate >= 90
                      ? "#22c55e"
                      : row.success_rate >= 70
                      ? "#f59e0b"
                      : "#ef4444",
                  }}
                />
                <span className="rate-label">{row.success_rate}%</span>
              </div>
            </td>
            <td>
              {row.failures > 0
                ? <span className="health-fail">{row.failures}</span>
                : <span className="health-ok">0</span>}
            </td>
            <td>{msLabel(row.avg_duration_ms)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LlmStatsPanel({ data }) {
  if (!data) return <p className="dash-loading">Loading…</p>;

  const stats = [
    { label: "Total LLM calls (7 d)", value: data.total_calls ?? "—", unit: "" },
    { label: "p50 response time",     value: msLabel(data.p50_ms),    unit: "" },
    { label: "p95 response time",     value: msLabel(data.p95_ms),    unit: "" },
    { label: "Fastest call",          value: msLabel(data.min_ms),    unit: "" },
    { label: "Slowest call",          value: msLabel(data.max_ms),    unit: "" },
  ];

  return (
    <div className="stat-grid">
      {stats.map((s) => (
        <div key={s.label} className="stat-card">
          <div className="stat-label">{s.label}</div>
          <div className="stat-value">{s.value}{s.unit && <span className="stat-unit">{s.unit}</span>}</div>
        </div>
      ))}
    </div>
  );
}

function TokenChart({ data }) {
  if (!data) return <p className="dash-loading">Loading…</p>;
  if (data.every((d) => d.total_tokens === 0))
    return <p className="health-empty">No token usage recorded yet.</p>;

  const maxTokens = Math.max(...data.map((d) => d.total_tokens), 1);

  return (
    <div className="token-chart">
      {data.map((d) => (
        <div key={d.date} className="token-col">
          <div className="token-bar-wrap">
            <div
              className="token-bar"
              style={{ height: `${Math.round((d.total_tokens / maxTokens) * 100)}%` }}
              title={`${d.total_tokens.toLocaleString()} tokens`}
            />
          </div>
          <div className="token-count">
            {d.total_tokens > 999
              ? `${(d.total_tokens / 1000).toFixed(1)}k`
              : d.total_tokens || "—"}
          </div>
          <div className="token-date">{shortDate(d.date)}</div>
        </div>
      ))}
    </div>
  );
}

function ErrorLogPanel({ data }) {
  if (!data) return <p className="dash-loading">Loading…</p>;
  if (data.length === 0) return <p className="health-empty health-ok-msg">No errors in the log.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Type</th>
          <th>User</th>
          <th>Session</th>
          <th>Context</th>
        </tr>
      </thead>
      <tbody>
        {data.map((e, i) => (
          <tr key={i}>
            <td className="health-ts">{fmt(e.ts)}</td>
            <td><span className="health-err-badge">{e.error ?? "unknown"}</span></td>
            <td className="health-mono">{e.user_id}</td>
            <td className="health-mono">{e.session_id}</td>
            <td className="health-err-msg">{e.message ?? (e.step != null ? `step ${e.step}` : "—")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentHealthPage() {
  const [tools,  setTools]  = useState(null);
  const [llm,    setLlm]    = useState(null);
  const [tokens, setTokens] = useState(null);
  const [errors, setErrors] = useState(null);

  useEffect(() => {
    fetchHealthTools().then(setTools).catch(() => setTools([]));
    fetchHealthLlm().then(setLlm).catch(() => setLlm({}));
    fetchHealthTokens().then(setTokens).catch(() => setTokens([]));
    fetchHealthErrors().then(setErrors).catch(() => setErrors([]));
  }, []);

  return (
    <>
      <h1 className="dash-title">Agent Health</h1>

      <section className="health-section">
        <h2 className="health-section-title">LLM Response Time</h2>
        <p className="health-section-sub">Last 7 days</p>
        <LlmStatsPanel data={llm} />
      </section>

      <section className="health-section">
        <h2 className="health-section-title">Tool Success / Failure Rate</h2>
        <p className="health-section-sub">Last 30 days</p>
        <ToolHealthPanel data={tools} />
      </section>

      <section className="health-section">
        <h2 className="health-section-title">Token Usage per Day</h2>
        <p className="health-section-sub">Last 7 days — total tokens billed to Groq</p>
        <TokenChart data={tokens} />
      </section>

      <section className="health-section">
        <h2 className="health-section-title">Error Log</h2>
        <p className="health-section-sub">Last 20 errors</p>
        <ErrorLogPanel data={errors} />
      </section>
    </>
  );
}
