import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchTickets, updateTicketStatus } from "../services/api";

const ALL_STATUSES = ["open", "in_progress", "escalated", "resolved", "closed"];

const STATUS_LABEL = {
  open:        "Open",
  in_progress: "In Progress",
  resolved:    "Resolved",
  escalated:   "Escalated",
  closed:      "Closed",
};

function ConfirmModal({ ticket, nextStatus, onConfirm, onCancel, saving }) {
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Confirm status change</h3>
        <p className="modal-body">
          Change ticket <strong>#{ticket.id}</strong> from{" "}
          <span className={`badge badge-${ticket.status}`}>{STATUS_LABEL[ticket.status]}</span>{" "}
          to{" "}
          <span className={`badge badge-${nextStatus}`}>{STATUS_LABEL[nextStatus]}</span>?
        </p>
        <p className="modal-warning">This will be saved immediately.</p>
        <div className="modal-actions">
          <button className="btn btn-outline" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={onConfirm} disabled={saving}>
            {saving ? "Saving…" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TicketsPage() {
  const [tickets, setTickets]   = useState([]);
  const [filter, setFilter]     = useState("all");
  const [loading, setLoading]   = useState(true);
  const [pending, setPending]   = useState(null); // { ticket, nextStatus }
  const [saving, setSaving]     = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    fetchTickets(filter === "all" ? "" : filter)
      .then(setTickets)
      .finally(() => setLoading(false));
  }, [filter]);

  function requestChange(ticket, nextStatus) {
    if (nextStatus === ticket.status) return;
    setPending({ ticket, nextStatus });
  }

  async function confirmChange() {
    setSaving(true);
    try {
      const updated = await updateTicketStatus(pending.ticket.id, pending.nextStatus);
      setTickets((prev) =>
        prev.map((t) => (t.id === updated.id ? updated : t))
      );
      setPending(null);
    } finally {
      setSaving(false);
    }
  }

  const visible = tickets;

  return (
    <>
      {pending && (
        <ConfirmModal
          ticket={pending.ticket}
          nextStatus={pending.nextStatus}
          onConfirm={confirmChange}
          onCancel={() => setPending(null)}
          saving={saving}
        />
      )}

      <h1 className="dash-title">Tickets</h1>

      <div className="filter-bar">
        <button
          className={`btn btn-sm ${filter === "all" ? "btn-primary" : "btn-outline"}`}
          onClick={() => setFilter("all")}
        >
          All
        </button>
        {ALL_STATUSES.map((s) => (
          <button
            key={s}
            className={`btn btn-sm ${filter === s ? "btn-primary" : "btn-outline"}`}
            onClick={() => setFilter(s)}
          >
            {STATUS_LABEL[s]}
          </button>
        ))}
        <span className="conv-count">
          {visible.length} ticket{visible.length !== 1 ? "s" : ""}
        </span>
      </div>

      {loading ? (
        <p className="dash-loading">Loading tickets…</p>
      ) : visible.length === 0 ? (
        <p className="conv-empty">No tickets found.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>User</th>
              <th>Issue</th>
              <th>Status</th>
              <th>Created</th>
              <th>Change status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <tr key={t.id}>
                <td className="ticket-id">#{t.id}</td>
                <td>
                  <span className="ticket-user">{t.username ? `@${t.username}` : t.chat_id}</span>
                </td>
                <td className="ticket-msg">{t.message}</td>
                <td>
                  <span className={`badge badge-${t.status}`}>{STATUS_LABEL[t.status] ?? t.status}</span>
                </td>
                <td className="ticket-date">
                  {new Date(t.created_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                </td>
                <td>
                  <select
                    className="status-select"
                    value={t.status}
                    onChange={(e) => requestChange(t, e.target.value)}
                  >
                    {ALL_STATUSES.map((s) => (
                      <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <button className="btn btn-sm btn-outline" onClick={() => navigate(`/tickets/${t.id}`)}>
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
