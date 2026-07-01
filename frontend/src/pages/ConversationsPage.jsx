import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchConversations } from "../services/api";

function timeAgo(isoStr) {
  if (!isoStr) return "—";
  const diff = (Date.now() - new Date(isoStr)) / 1000;
  if (diff < 60)  return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return new Date(isoStr).toLocaleDateString();
}

const OUTCOME_CLASS = {
  resolved:  "badge badge-resolved",
  escalated: "badge badge-escalated",
  abandoned: "badge badge-abandoned",
  open:      "badge badge-open",
};

export default function ConversationsPage() {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter]   = useState("all");
  const navigate = useNavigate();

  useEffect(() => {
    fetchConversations()
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, []);

  const visible = filter === "all" ? rows : rows.filter((r) => r.outcome === filter);

  if (loading) return <p className="dash-loading">Loading conversations…</p>;

  return (
    <>
      <h1 className="dash-title">Conversations</h1>

      <div className="filter-bar">
        {["all", "open", "resolved", "escalated", "abandoned"].map((v) => (
          <button
            key={v}
            className={`btn btn-sm ${filter === v ? "btn-primary" : "btn-outline"}`}
            onClick={() => setFilter(v)}
          >
            {v.charAt(0).toUpperCase() + v.slice(1)}
          </button>
        ))}
        <span className="conv-count">{visible.length} session{visible.length !== 1 ? "s" : ""}</span>
      </div>

      {visible.length === 0 ? (
        <p className="conv-empty">No conversations found.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Started</th>
              <th>Turns</th>
              <th>Outcome</th>
              <th>Last message</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr
                key={row.session_id}
                className="conv-row"
                onClick={() => navigate(`/conversations/${encodeURIComponent(row.session_id)}`)}
              >
                <td className="conv-user">
                  <span className="conv-uid">{row.user_id}</span>
                  <span className="conv-session-label">{row.session_id}</span>
                </td>
                <td>{timeAgo(row.started_at)}</td>
                <td>{row.turns}</td>
                <td>
                  <span className={OUTCOME_CLASS[row.outcome] || "badge badge-open"}>
                    {row.outcome}
                  </span>
                </td>
                <td className="conv-preview">{row.last_message || <em className="conv-empty-msg">—</em>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
