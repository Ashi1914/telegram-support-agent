import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchConversation } from "../services/api";

function fmt(isoStr) {
  if (!isoStr) return "";
  return new Date(isoStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function truncate(text, n = 80) {
  if (!text) return "";
  return text.length > n ? text.slice(0, n) + "…" : text;
}

function EventCard({ event }) {
  const { type, payload, ts } = event;

  if (type === "message_received") {
    return (
      <div className="evt evt-user">
        <div className="evt-label">User</div>
        <div className="evt-bubble evt-bubble--user">{payload.text}</div>
        <div className="evt-ts">{fmt(ts)}</div>
      </div>
    );
  }

  if (type === "agent_response") {
    return (
      <div className="evt evt-agent">
        <div className="evt-label">Agent</div>
        <div className="evt-bubble evt-bubble--agent">{payload.response}</div>
        <div className="evt-ts">{fmt(ts)}</div>
      </div>
    );
  }

  if (type === "thought") {
    return (
      <div className="evt evt-thought">
        <span className="evt-chip evt-chip--thought">Thought</span>
        <span className="evt-thought-text">{payload.text}</span>
        <span className="evt-ts">{fmt(ts)}</span>
      </div>
    );
  }

  if (type === "tool_call") {
    return (
      <div className="evt evt-tool">
        <div className="evt-tool-header">
          <span className="evt-chip evt-chip--tool">Tool call</span>
          <span className="evt-tool-name">{payload.tool}</span>
          <span className="evt-ts">{fmt(ts)}</span>
        </div>
        {payload.input && (
          <pre className="evt-code">{JSON.stringify(payload.input, null, 2)}</pre>
        )}
      </div>
    );
  }

  if (type === "tool_result") {
    const content = typeof payload.result === "string"
      ? payload.result
      : JSON.stringify(payload.result, null, 2);
    return (
      <div className="evt evt-result">
        <div className="evt-tool-header">
          <span className="evt-chip evt-chip--result">Tool result</span>
          <span className="evt-ts">{fmt(ts)}</span>
        </div>
        <pre className="evt-code evt-code--result">{truncate(content, 400)}</pre>
      </div>
    );
  }

  if (type === "error") {
    return (
      <div className="evt evt-error">
        <span className="evt-chip evt-chip--error">Error</span>
        <span className="evt-error-text">{payload.error || JSON.stringify(payload)}</span>
        <span className="evt-ts">{fmt(ts)}</span>
      </div>
    );
  }

  // fallback for unknown event types
  return (
    <div className="evt evt-unknown">
      <span className="evt-chip">{type}</span>
      <pre className="evt-code">{JSON.stringify(payload, null, 2)}</pre>
      <span className="evt-ts">{fmt(ts)}</span>
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
      .catch(() => setError("Conversation not found."))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <p className="dash-loading">Loading transcript…</p>;
  if (error)   return <p className="dash-loading">{error}</p>;

  return (
    <>
      <div className="transcript-header">
        <button className="btn btn-sm btn-outline" onClick={() => navigate("/conversations")}>
          ← Back
        </button>
        <div className="transcript-meta">
          <span className="transcript-user">User {conv.user_id}</span>
          <span className="transcript-session">Session: {conv.session_id}</span>
          <span className="transcript-turns">{conv.turns} turn{conv.turns !== 1 ? "s" : ""}</span>
        </div>
      </div>

      <div className="transcript">
        {conv.events.length === 0 ? (
          <p className="conv-empty">No events recorded for this session.</p>
        ) : (
          conv.events.map((evt, i) => <EventCard key={i} event={evt} />)
        )}
      </div>
    </>
  );
}
