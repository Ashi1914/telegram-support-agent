import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchTickets, updateTicketStatus } from "../services/api";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { StatusBadge, STATUS_LABEL } from "@/components/StatusBadge";

const ALL_STATUSES = ["open", "in_progress", "escalated", "resolved", "closed"];

function ErrorState({ message, onRetry }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-8 text-center">
      <p className="text-sm text-red-600 mb-3">{message}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export default function TicketsPage() {
  const [tickets, setTickets]       = useState([]);
  const [filter, setFilter]         = useState("all");
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [pending, setPending]       = useState(null); // { ticket, nextStatus }
  const [revertError, setRevertError] = useState(null);
  const navigate = useNavigate();

  const load = (f) => {
    setLoading(true);
    setError(null);
    fetchTickets(f === "all" ? "" : f)
      .then(setTickets)
      .catch(() => setError("Failed to load tickets. Check that the API is running."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(filter); }, [filter]);

  function requestChange(ticket, nextStatus) {
    if (nextStatus === ticket.status) return;
    setRevertError(null);
    setPending({ ticket, nextStatus });
  }

  async function confirmChange() {
    const { ticket, nextStatus } = pending;

    // Optimistic update — close dialog and update UI immediately
    setTickets((prev) =>
      prev.map((t) => t.id === ticket.id ? { ...t, status: nextStatus } : t)
    );
    setPending(null);

    // Persist in background; revert on failure
    try {
      await updateTicketStatus(ticket.id, nextStatus);
    } catch {
      setTickets((prev) =>
        prev.map((t) => t.id === ticket.id ? { ...t, status: ticket.status } : t)
      );
      setRevertError(`Failed to update ticket #${ticket.id}. Status has been reverted.`);
    }
  }

  return (
    <>
      {/* ── Confirm dialog ──────────────────────────────────────────────────── */}
      <Dialog open={!!pending} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm status change</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 pt-1">
                <p>
                  Change ticket <strong>#{pending?.ticket.id}</strong> from{" "}
                  <StatusBadge status={pending?.ticket.status} />{" "}
                  to <StatusBadge status={pending?.nextStatus} />?
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

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Tickets</h1>
        <span className="text-sm text-muted-foreground">{tickets.length} ticket{tickets.length !== 1 ? "s" : ""}</span>
      </div>

      {/* ── Revert error banner ─────────────────────────────────────────────── */}
      {revertError && (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 mb-4 text-sm text-red-600">
          <span>{revertError}</span>
          <Button variant="ghost" size="sm" className="text-red-600 hover:text-red-700 h-auto py-0" onClick={() => setRevertError(null)}>✕</Button>
        </div>
      )}

      {/* ── Filter bar ──────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2 mb-5">
        <Button size="sm" variant={filter === "all" ? "default" : "outline"} onClick={() => setFilter("all")}>All</Button>
        {ALL_STATUSES.map((s) => (
          <Button key={s} size="sm" variant={filter === s ? "default" : "outline"} onClick={() => setFilter(s)}>
            {STATUS_LABEL[s]}
          </Button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-12 rounded bg-muted" />)}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => load(filter)} />
      ) : tickets.length === 0 ? (
        <p className="text-center py-12 text-muted-foreground text-sm">No tickets found.</p>
      ) : (
        <div className="rounded-xl border bg-card shadow-sm">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">#</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Issue</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Change status</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tickets.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-medium text-muted-foreground">#{t.id}</TableCell>
                  <TableCell className="font-medium">{t.username ? `@${t.username}` : t.chat_id}</TableCell>
                  <TableCell className="max-w-xs truncate text-muted-foreground">{t.message}</TableCell>
                  <TableCell><StatusBadge status={t.status} /></TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap text-xs">
                    {new Date(t.created_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                  </TableCell>
                  <TableCell>
                    <Select value={t.status} onValueChange={(val) => requestChange(t, val)}>
                      <SelectTrigger className="h-8 w-36 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ALL_STATUSES.map((s) => (
                          <SelectItem key={s} value={s}>{STATUS_LABEL[s]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Button size="sm" variant="outline" onClick={() => navigate(`/tickets/${t.id}`)}>View</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
