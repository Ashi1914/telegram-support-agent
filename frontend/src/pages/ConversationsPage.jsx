import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchConversations } from "../services/api";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { StatusBadge, STATUS_LABEL } from "@/components/StatusBadge";

const OUTCOME_FILTERS = ["all", "open", "resolved", "escalated", "abandoned"];

function timeAgo(isoStr) {
  if (!isoStr) return "—";
  const diff = (Date.now() - new Date(isoStr)) / 1000;
  if (diff < 60)   return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return new Date(isoStr).toLocaleDateString();
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-8 text-center">
      <p className="text-sm text-red-600 mb-3">{message}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export default function ConversationsPage() {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [filter, setFilter]   = useState("all");
  const navigate = useNavigate();

  const load = () => {
    setLoading(true);
    setError(null);
    fetchConversations()
      .then(setRows)
      .catch(() => setError("Failed to load conversations. Check that the API is running."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const visible = filter === "all" ? rows : rows.filter((r) => r.outcome === filter);

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Conversations</h1>
        <span className="text-sm text-muted-foreground">{visible.length} session{visible.length !== 1 ? "s" : ""}</span>
      </div>

      <div className="flex flex-wrap gap-2 mb-5">
        {OUTCOME_FILTERS.map((f) => (
          <Button
            key={f}
            size="sm"
            variant={filter === f ? "default" : "outline"}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? "All" : STATUS_LABEL[f] ?? f.charAt(0).toUpperCase() + f.slice(1)}
          </Button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2 animate-pulse">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-12 rounded bg-muted" />)}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : visible.length === 0 ? (
        <p className="text-center py-12 text-muted-foreground text-sm">No conversations found.</p>
      ) : (
        <div className="rounded-xl border bg-card shadow-sm">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Started</TableHead>
                <TableHead className="w-20 text-center">Turns</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Last message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow
                  key={row.session_id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/conversations/${encodeURIComponent(row.session_id)}`)}
                >
                  <TableCell>
                    <span className="font-semibold text-sm block">{row.user_id}</span>
                    <span className="text-xs text-muted-foreground">{row.session_id}</span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{timeAgo(row.started_at)}</TableCell>
                  <TableCell className="text-center text-sm">{row.turns}</TableCell>
                  <TableCell><StatusBadge status={row.outcome} /></TableCell>
                  <TableCell className="max-w-xs truncate text-sm text-muted-foreground">
                    {row.last_message || <em className="text-muted-foreground/40">—</em>}
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
