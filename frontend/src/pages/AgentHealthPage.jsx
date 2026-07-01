import { useEffect, useState } from "react";
import { fetchHealthTools, fetchHealthLlm, fetchHealthTokens, fetchHealthErrors } from "../services/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 30_000; // 30 s → failures visible within 1 minute

function msLabel(ms) {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function fmtTs(isoStr) {
  if (!isoStr) return "—";
  return new Date(isoStr).toLocaleString([], {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function timeAgo(date) {
  if (!date) return "";
  const diff = Math.round((Date.now() - date) / 1000);
  if (diff < 5)  return "just now";
  if (diff < 60) return `${diff}s ago`;
  return `${Math.round(diff / 60)}m ago`;
}

function shortDate(dateStr) {
  return new Date(dateStr + "T12:00:00Z").toLocaleDateString([], { month: "short", day: "numeric" });
}

function SectionError({ message, onRetry }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-5 text-center">
      <p className="text-xs text-red-600 mb-2">{message}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

// ── LLM Stats ─────────────────────────────────────────────────────────────────

function LlmSection({ data, error, onRetry }) {
  if (error) return <SectionError message={error} onRetry={onRetry} />;
  if (!data)  return <div className="grid grid-cols-3 gap-4 animate-pulse">{Array.from({length:5}).map((_,i)=><div key={i} className="h-20 rounded-xl bg-muted"/>)}</div>;

  const stats = [
    { label: "Total calls (7 d)", value: data.total_calls ?? "—" },
    { label: "p50 response time",  value: msLabel(data.p50_ms) },
    { label: "p95 response time",  value: msLabel(data.p95_ms) },
    { label: "Fastest",            value: msLabel(data.min_ms) },
    { label: "Slowest",            value: msLabel(data.max_ms) },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {stats.map((s) => (
        <Card key={s.label}>
          <CardContent className="pt-5 pb-4">
            <p className="text-[0.65rem] font-medium uppercase tracking-widest text-muted-foreground mb-1.5">{s.label}</p>
            <p className="text-2xl font-bold">{s.value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Tool Health ───────────────────────────────────────────────────────────────

function ToolSection({ data, error, onRetry }) {
  if (error) return <SectionError message={error} onRetry={onRetry} />;
  if (!data)  return <div className="h-32 rounded-xl bg-muted animate-pulse" />;
  if (data.length === 0) return <p className="text-sm text-muted-foreground py-4">No tool calls recorded yet.</p>;

  return (
    <div className="rounded-xl border bg-card shadow-sm">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Tool</TableHead>
            <TableHead className="w-24 text-center">Total</TableHead>
            <TableHead>Success rate</TableHead>
            <TableHead className="w-24 text-center">Failures</TableHead>
            <TableHead className="w-32 text-right">Avg duration</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((row) => (
            <TableRow key={row.tool}>
              <TableCell className="font-semibold text-sm">{row.tool}</TableCell>
              <TableCell className="text-center text-sm">{row.total}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        row.success_rate >= 90 ? "bg-green-500"
                          : row.success_rate >= 70 ? "bg-amber-400"
                          : "bg-red-500"
                      )}
                      style={{ width: `${row.success_rate}%` }}
                    />
                  </div>
                  <span className="text-xs font-semibold w-10 text-right">{row.success_rate}%</span>
                </div>
              </TableCell>
              <TableCell className="text-center text-sm">
                <span className={row.failures > 0 ? "text-red-600 font-semibold" : "text-green-600 font-semibold"}>
                  {row.failures}
                </span>
              </TableCell>
              <TableCell className="text-right text-sm text-muted-foreground">{msLabel(row.avg_duration_ms)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Token Chart ───────────────────────────────────────────────────────────────

function TokenSection({ data, error, onRetry }) {
  if (error) return <SectionError message={error} onRetry={onRetry} />;
  if (!data)  return <div className="h-40 rounded-xl bg-muted animate-pulse" />;
  if (data.every((d) => d.total_tokens === 0))
    return <p className="text-sm text-muted-foreground py-4">No token usage recorded yet.</p>;

  const maxTokens = Math.max(...data.map((d) => d.total_tokens), 1);

  return (
    <div className="flex items-end gap-2 h-36">
      {data.map((d) => {
        const pct = Math.max(Math.round((d.total_tokens / maxTokens) * 100), d.total_tokens > 0 ? 2 : 0);
        return (
          <div key={d.date} className="flex flex-col items-center flex-1 gap-1 h-full">
            <div className="flex-1 flex items-end w-full">
              <div className="w-full bg-primary rounded-t transition-all" style={{ height: `${pct}%` }}
                title={`${d.total_tokens.toLocaleString()} tokens`} />
            </div>
            <span className="text-[0.6rem] text-muted-foreground whitespace-nowrap">
              {d.total_tokens > 999 ? `${(d.total_tokens / 1000).toFixed(1)}k` : d.total_tokens || "—"}
            </span>
            <span className="text-[0.6rem] text-muted-foreground/60 whitespace-nowrap">{shortDate(d.date)}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Error Log ─────────────────────────────────────────────────────────────────

function ErrorLogSection({ data, error, onRetry }) {
  if (error) return <SectionError message={error} onRetry={onRetry} />;
  if (!data)  return <div className="h-24 rounded-xl bg-muted animate-pulse" />;
  if (data.length === 0) return <p className="text-sm text-green-600 py-4">No errors in the log.</p>;

  return (
    <div className="rounded-xl border bg-card shadow-sm">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>User</TableHead>
            <TableHead>Session</TableHead>
            <TableHead>Context</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((e, i) => (
            <TableRow key={i}>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{fmtTs(e.ts)}</TableCell>
              <TableCell>
                <span className="inline-flex items-center rounded-full bg-red-100 text-red-700 px-2 py-0.5 text-xs font-semibold">
                  {e.error ?? "unknown"}
                </span>
              </TableCell>
              <TableCell className="text-xs font-mono text-muted-foreground">{e.user_id}</TableCell>
              <TableCell className="text-xs font-mono text-muted-foreground">{e.session_id}</TableCell>
              <TableCell className="text-xs text-muted-foreground max-w-xs truncate">
                {e.message ?? (e.step != null ? `step ${e.step}` : "—")}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentHealthPage() {
  const [tools,     setTools]     = useState(null);
  const [toolsErr,  setToolsErr]  = useState(null);
  const [llm,       setLlm]       = useState(null);
  const [llmErr,    setLlmErr]    = useState(null);
  const [tokens,    setTokens]    = useState(null);
  const [tokensErr, setTokensErr] = useState(null);
  const [errors,    setErrors]    = useState(null);
  const [errorsErr, setErrorsErr] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadAll = () => {
    setToolsErr(null);
    setLlmErr(null);
    setTokensErr(null);
    setErrorsErr(null);

    fetchHealthTools().then(setTools).catch(()   => setToolsErr("Failed to load tool stats."));
    fetchHealthLlm().then(setLlm).catch(()       => setLlmErr("Failed to load LLM stats."));
    fetchHealthTokens().then(setTokens).catch(() => setTokensErr("Failed to load token usage."));
    fetchHealthErrors().then(setErrors).catch(() => setErrorsErr("Failed to load error log."));
    setLastUpdated(new Date());
  };

  useEffect(() => {
    loadAll();
    // Poll every 30 s so tool failures appear within 1 minute of occurring
    const id = setInterval(loadAll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []); // state setters are stable; no deps needed

  const Section = ({ title, sub, children }) => (
    <Card className="mb-6">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
        {sub && <CardDescription>{sub}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );

  return (
    <>
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-bold">Agent Health</h1>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-muted-foreground">Updated {timeAgo(lastUpdated)}</span>
          )}
          <Button size="sm" variant="outline" onClick={loadAll}>Refresh now</Button>
        </div>
      </div>

      <Section title="LLM Response Time" sub="Last 7 days">
        <LlmSection data={llm} error={llmErr} onRetry={() => { setLlmErr(null); fetchHealthLlm().then(setLlm).catch(() => setLlmErr("Failed.")); }} />
      </Section>

      <Section title="Tool Success / Failure Rate" sub="Last 30 days · auto-refreshes every 30 s">
        <ToolSection data={tools} error={toolsErr} onRetry={() => { setToolsErr(null); fetchHealthTools().then(setTools).catch(() => setToolsErr("Failed.")); }} />
      </Section>

      <Section title="Token Usage per Day" sub="Last 7 days — total tokens billed to Groq">
        <TokenSection data={tokens} error={tokensErr} onRetry={() => { setTokensErr(null); fetchHealthTokens().then(setTokens).catch(() => setTokensErr("Failed.")); }} />
      </Section>

      <Section title="Error Log" sub="Last 20 errors · auto-refreshes every 30 s">
        <ErrorLogSection data={errors} error={errorsErr} onRetry={() => { setErrorsErr(null); fetchHealthErrors().then(setErrors).catch(() => setErrorsErr("Failed.")); }} />
      </Section>
    </>
  );
}
