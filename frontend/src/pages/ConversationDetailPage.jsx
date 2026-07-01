import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchConversation } from "../services/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function fmt(isoStr) {
  if (!isoStr) return "";
  return new Date(isoStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function truncate(text, n = 400) {
  if (!text) return "";
  return text.length > n ? text.slice(0, n) + "…" : text;
}

function EventCard({ event }) {
  const { type, payload, ts } = event;

  if (type === "message_received") {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-[0.65rem] font-semibold uppercase tracking-widest text-muted-foreground">User</span>
        <div className="bg-slate-100 text-slate-800 rounded-xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed max-w-prose whitespace-pre-wrap">
          {payload.text}
        </div>
        <span className="text-[0.65rem] text-muted-foreground/60">{fmt(ts)}</span>
      </div>
    );
  }

  if (type === "agent_response") {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-[0.65rem] font-semibold uppercase tracking-widest text-muted-foreground">Agent</span>
        <div className="bg-slate-900 text-slate-100 rounded-xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed max-w-prose whitespace-pre-wrap">
          {payload.response}
        </div>
        <span className="text-[0.65rem] text-muted-foreground/60">{fmt(ts)}</span>
      </div>
    );
  }

  if (type === "thought") {
    return (
      <div className="flex items-baseline gap-2 border-l-2 border-amber-400 pl-3 py-1 bg-amber-50 rounded-r-md flex-wrap">
        <span className="text-[0.62rem] font-bold uppercase tracking-wider bg-amber-200 text-amber-900 px-1.5 py-0.5 rounded-full flex-shrink-0">Thought</span>
        <span className="text-xs text-amber-800 italic flex-1">{payload.text}</span>
        <span className="text-[0.62rem] text-muted-foreground/60 flex-shrink-0">{fmt(ts)}</span>
      </div>
    );
  }

  if (type === "tool_call") {
    return (
      <div className="border-l-2 border-indigo-400 pl-3 py-2 bg-indigo-50 rounded-r-md space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[0.62rem] font-bold uppercase tracking-wider bg-indigo-200 text-indigo-900 px-1.5 py-0.5 rounded-full">Tool call</span>
          <span className="text-xs font-semibold text-indigo-700">{payload.tool}</span>
          <span className="text-[0.62rem] text-muted-foreground/60 ml-auto">{fmt(ts)}</span>
        </div>
        {payload.input && (
          <pre className="evt-code bg-indigo-100/60 text-indigo-900 rounded p-2">
            {JSON.stringify(payload.input, null, 2)}
          </pre>
        )}
      </div>
    );
  }

  if (type === "tool_result") {
    const content = typeof payload.result === "string"
      ? payload.result
      : JSON.stringify(payload.result, null, 2);
    return (
      <div className="border-l-2 border-green-400 pl-3 py-2 bg-green-50 rounded-r-md space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[0.62rem] font-bold uppercase tracking-wider bg-green-200 text-green-900 px-1.5 py-0.5 rounded-full">Tool result</span>
          <span className="text-[0.62rem] text-muted-foreground/60 ml-auto">{fmt(ts)}</span>
        </div>
        <pre className="evt-code bg-green-100/60 text-green-900 rounded p-2">{truncate(content)}</pre>
      </div>
    );
  }

  if (type === "error") {
    return (
      <div className="flex items-baseline gap-2 border-l-2 border-red-400 pl-3 py-1 bg-red-50 rounded-r-md flex-wrap">
        <span className="text-[0.62rem] font-bold uppercase tracking-wider bg-red-200 text-red-900 px-1.5 py-0.5 rounded-full flex-shrink-0">Error</span>
        <span className="text-xs text-red-700 flex-1">{payload.error ?? JSON.stringify(payload)}</span>
        <span className="text-[0.62rem] text-muted-foreground/60 flex-shrink-0">{fmt(ts)}</span>
      </div>
    );
  }

  return (
    <div className="border-l-2 border-muted pl-3 py-1 bg-muted/30 rounded-r-md flex items-center gap-2 flex-wrap">
      <span className="text-[0.62rem] font-bold uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-full">{type}</span>
      <pre className="evt-code text-xs flex-1">{JSON.stringify(payload, null, 2)}</pre>
      <span className="text-[0.62rem] text-muted-foreground/60">{fmt(ts)}</span>
    </div>
  );
}

export default function ConversationDetailPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [conv, setConv]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    fetchConversation(sessionId)
      .then(setConv)
      .catch(() => setError("Conversation not found or the API is unavailable."))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return (
    <div className="space-y-3 animate-pulse max-w-2xl">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-14 rounded-xl bg-muted" style={{ opacity: 1 - i * 0.12 }} />
      ))}
    </div>
  );

  if (error) return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-8 text-center max-w-lg">
      <p className="text-sm text-red-600 mb-3">{error}</p>
      <Button variant="outline" size="sm" onClick={() => navigate("/conversations")}>← Back to conversations</Button>
    </div>
  );

  return (
    <>
      <div className="flex items-center gap-4 mb-6">
        <Button variant="outline" size="sm" onClick={() => navigate("/conversations")}>← Back</Button>
        <div className="flex items-center gap-3 min-w-0">
          <span className="font-bold truncate">User {conv.user_id}</span>
          <span className="text-muted-foreground text-xs flex-shrink-0">Session: {conv.session_id}</span>
          <span className="text-muted-foreground text-xs flex-shrink-0">{conv.turns} turn{conv.turns !== 1 ? "s" : ""}</span>
        </div>
      </div>

      <div className="flex flex-col gap-3 max-w-2xl">
        {conv.events.length === 0 ? (
          <p className="text-center py-10 text-muted-foreground text-sm">No events recorded for this session.</p>
        ) : (
          conv.events.map((evt, i) => <EventCard key={i} event={evt} />)
        )}
      </div>
    </>
  );
}
