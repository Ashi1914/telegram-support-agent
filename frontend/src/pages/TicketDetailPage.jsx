import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchTicket, updateTicketStatus } from "../services/api";

export default function TicketDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [ticket, setTicket] = useState(null);

  useEffect(() => {
    fetchTicket(id).then(setTicket);
  }, [id]);

  const handleStatus = async (status) => {
    const updated = await updateTicketStatus(id, status);
    setTicket(updated);
  };

  if (!ticket) return <p>Loading...</p>;

  return (
    <div>
      <button className="btn" onClick={() => navigate(-1)} style={{ marginBottom: 20 }}>
        ← Back
      </button>
      <div className="card">
        <h2>Customer Message</h2>
        <p>{ticket.message}</p>
      </div>
      <div className="card">
        <h2>AI Response</h2>
        <p>{ticket.ai_response ?? "No response yet."}</p>
      </div>
      <div className="card">
        <h2>Status: <span className={`badge badge-${ticket.status}`}>{ticket.status}</span></h2>
        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
          <button className="btn btn-primary" onClick={() => handleStatus("resolved")}>Mark Resolved</button>
          <button className="btn btn-primary" onClick={() => handleStatus("escalated")}>Escalate</button>
          <button className="btn btn-primary" onClick={() => handleStatus("open")}>Reopen</button>
        </div>
      </div>
    </div>
  );
}
