import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchTicket, updateTicketStatus } from "../services/api";

const STATUS_LABEL = {
  open:        "Open",
  in_progress: "In Progress",
  resolved:    "Resolved",
  escalated:   "Escalated",
  closed:      "Closed",
};

const STATUS_ACTIONS = [
  { value: "open",        label: "Reopen" },
  { value: "in_progress", label: "Mark In Progress" },
  { value: "resolved",    label: "Mark Resolved" },
  { value: "escalated",   label: "Escalate" },
  { value: "closed",      label: "Close" },
];

function ConfirmModal({ fromStatus, toStatus, onConfirm, onCancel, saving }) {
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Confirm status change</h3>
        <p className="modal-body">
          Change status from{" "}
          <span className={`badge badge-${fromStatus}`}>{STATUS_LABEL[fromStatus]}</span>{" "}
          to{" "}
          <span className={`badge badge-${toStatus}`}>{STATUS_LABEL[toStatus]}</span>?
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

export default function TicketDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [ticket, setTicket]   = useState(null);
  const [pending, setPending] = useState(null); // nextStatus string
  const [saving, setSaving]   = useState(false);

  useEffect(() => {
    fetchTicket(id).then(setTicket);
  }, [id]);

  async function confirmChange() {
    setSaving(true);
    try {
      const updated = await updateTicketStatus(id, pending);
      setTicket(updated);
      setPending(null);
    } finally {
      setSaving(false);
    }
  }

  if (!ticket) return <p className="dash-loading">Loading…</p>;

  const availableActions = STATUS_ACTIONS.filter((a) => a.value !== ticket.status);

  return (
    <>
      {pending && (
        <ConfirmModal
          fromStatus={ticket.status}
          toStatus={pending}
          onConfirm={confirmChange}
          onCancel={() => setPending(null)}
          saving={saving}
        />
      )}

      <div className="transcript-header">
        <button className="btn btn-sm btn-outline" onClick={() => navigate("/tickets")}>
          ← Back
        </button>
        <div className="transcript-meta">
          <span className="transcript-user">
            {ticket.username ? `@${ticket.username}` : ticket.chat_id}
          </span>
          <span className="transcript-session">Ticket #{ticket.id}</span>
          <span className={`badge badge-${ticket.status}`}>
            {STATUS_LABEL[ticket.status] ?? ticket.status}
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Customer message</h2>
        <p>{ticket.message}</p>
      </div>

      {ticket.ai_response && (
        <div className="card">
          <h2>AI response</h2>
          <p>{ticket.ai_response}</p>
        </div>
      )}

      <div className="card">
        <h2>Update status</h2>
        <div className="ticket-actions">
          {availableActions.map((a) => (
            <button
              key={a.value}
              className={`btn btn-sm ${a.value === "escalated" ? "btn-danger" : a.value === "closed" || a.value === "resolved" ? "btn-success" : "btn-outline"}`}
              onClick={() => setPending(a.value)}
            >
              {a.label}
            </button>
          ))}
        </div>
        <p className="ticket-updated">
          Last updated: {new Date(ticket.updated_at).toLocaleString()}
        </p>
      </div>
    </>
  );
}
