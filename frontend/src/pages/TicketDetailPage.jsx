import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchTicket, updateTicketStatus, replyToTicket } from "../services/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { StatusBadge, STATUS_LABEL } from "@/components/StatusBadge";

const ALL_STATUSES = ["open", "in_progress", "resolved", "escalated", "closed"];
const HANDED_OFF_STATUSES = ["escalated", "in_progress"];

const STATUS_VARIANT = {
  escalated:   "destructive",
  resolved:    "default",
  closed:      "secondary",
  in_progress: "outline",
  open:        "outline",
};

function ErrorState({ message, onRetry }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-8 text-center">
      <p className="text-sm text-red-600 mb-3">{message}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export default function TicketDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [ticket, setTicket]         = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [pending, setPending]       = useState(null); // nextStatus string
  const [revertError, setRevertError] = useState(null);
  const [replyText, setReplyText]   = useState("");
  const [sending, setSending]       = useState(false);
  const [replyError, setReplyError] = useState(null);
  const [replySent, setReplySent]   = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchTicket(id)
      .then(setTicket)
      .catch(() => setError("Could not load ticket. It may not exist or the API is unavailable."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [id]);

  async function confirmChange() {
    const nextStatus = pending;
    const prevStatus = ticket.status;

    // Optimistic update — reflect change instantly, close the dialog
    setTicket((t) => ({ ...t, status: nextStatus }));
    setPending(null);
    setRevertError(null);

    // Sync with server in background; revert if it fails
    try {
      const updated = await updateTicketStatus(id, nextStatus);
      setTicket(updated); // pull updated_at and any server-side fields
    } catch {
      setTicket((t) => ({ ...t, status: prevStatus }));
      setRevertError("Failed to save status change. It has been reverted.");
    }
  }

  async function sendReply() {
    const message = replyText.trim();
    if (!message || sending) return;

    setSending(true);
    setReplyError(null);
    setReplySent(false);
    try {
      await replyToTicket(id, message);
      setReplyText("");
      setReplySent(true);
    } catch {
      setReplyError("Failed to send reply. Please try again.");
    } finally {
      setSending(false);
    }
  }

  if (loading) return (
    <div className="space-y-4 animate-pulse max-w-2xl">
      <div className="h-8 w-32 rounded bg-muted" />
      <div className="h-32 rounded-xl bg-muted" />
      <div className="h-32 rounded-xl bg-muted" />
    </div>
  );

  if (error) return <ErrorState message={error} onRetry={load} />;

  const availableActions = ALL_STATUSES.filter((s) => s !== ticket.status);

  return (
    <>
      <Dialog open={!!pending} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm status change</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 pt-1">
                <p>
                  Change status from <StatusBadge status={ticket.status} /> to{" "}
                  <StatusBadge status={pending} />?
                </p>
                <p className="text-xs text-muted-foreground">This will be saved immediately.</p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPending(null)}>Cancel</Button>
            <Button onClick={confirmChange}>Confirm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="flex items-center gap-4 mb-6">
        <Button variant="outline" size="sm" onClick={() => navigate("/tickets")}>← Back</Button>
        <div className="flex items-center gap-3">
          <span className="font-bold">{ticket.username ? `@${ticket.username}` : ticket.chat_id}</span>
          <span className="text-muted-foreground text-sm">Ticket #{ticket.id}</span>
          <StatusBadge status={ticket.status} />
        </div>
      </div>

      {revertError && (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 mb-4 text-sm text-red-600 max-w-2xl">
          <span>{revertError}</span>
          <Button variant="ghost" size="sm" className="text-red-600 h-auto py-0" onClick={() => setRevertError(null)}>✕</Button>
        </div>
      )}

      <div className="space-y-4 max-w-2xl">
        <Card>
          <CardHeader><CardTitle className="text-base">Customer message</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground leading-relaxed">{ticket.message}</p>
          </CardContent>
        </Card>

        {ticket.ai_response && (
          <Card>
            <CardHeader><CardTitle className="text-base">AI response</CardTitle></CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground leading-relaxed">{ticket.ai_response}</p>
            </CardContent>
          </Card>
        )}

        {HANDED_OFF_STATUSES.includes(ticket.status) && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Reply to customer</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground mb-2">
                This conversation has been handed off from the AI — messages sent here go straight to the customer on Telegram.
              </p>
              <textarea
                className="w-full min-h-24 rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="Type a reply…"
                value={replyText}
                onChange={(e) => { setReplyText(e.target.value); setReplySent(false); }}
                disabled={sending}
              />
              <div className="flex items-center gap-3 mt-3">
                <Button size="sm" onClick={sendReply} disabled={sending || !replyText.trim()}>
                  {sending ? "Sending…" : "Send"}
                </Button>
                {replySent && <span className="text-xs text-green-600">Sent.</span>}
                {replyError && <span className="text-xs text-red-600">{replyError}</span>}
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader><CardTitle className="text-base">Update status</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {availableActions.map((s) => (
                <Button
                  key={s}
                  size="sm"
                  variant={STATUS_VARIANT[s] ?? "outline"}
                  onClick={() => { setRevertError(null); setPending(s); }}
                >
                  {STATUS_LABEL[s]}
                </Button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-4">
              Last updated: {new Date(ticket.updated_at).toLocaleString()}
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
