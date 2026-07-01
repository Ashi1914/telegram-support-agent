import { useCallback, useEffect, useState } from "react";
import { fetchDashboardFeed, fetchDashboardStats } from "../services/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const FEED_INTERVAL_MS = 10_000;

function timeAgo(isoStr) {
  const diff = (Date.now() - new Date(isoStr)) / 1000;
  if (diff < 60)    return `${Math.round(diff)}s ago`;
  if (diff < 3600)  return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return new Date(isoStr).toLocaleDateString();
}

function StatCard({ label, value, unit = "", highlight = false }) {
  return (
    <Card className={highlight ? "border-l-4 border-l-primary" : ""}>
      <CardContent className="pt-6">
        <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-2">{label}</p>
        <p className="text-4xl font-bold text-foreground leading-none">
          {value}
          {unit && <span className="text-xl font-medium text-muted-foreground ml-1">{unit}</span>}
        </p>
      </CardContent>
    </Card>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-8 text-center">
      <p className="text-sm text-red-600 mb-3">{message}</p>
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats]             = useState(null);
  const [feed, setFeed]               = useState([]);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState(null);
  const [feedPulse, setFeedPulse]     = useState(false);

  const loadAll = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([fetchDashboardStats(), fetchDashboardFeed()])
      .then(([s, f]) => {
        setStats(s);
        setFeed(f);
        setLastRefresh(new Date());
      })
      .catch(() => setError("Failed to load dashboard. Check that the API is running."))
      .finally(() => setLoading(false));
  }, []);

  const refreshFeed = useCallback(() => {
    fetchDashboardFeed()
      .then((data) => {
        setFeed(data);
        setLastRefresh(new Date());
        setFeedPulse(true);
        setTimeout(() => setFeedPulse(false), 600);
      })
      .catch(() => {});
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => {
    const id = setInterval(refreshFeed, FEED_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refreshFeed]);

  if (loading) return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5 animate-pulse">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-28 rounded-xl bg-muted" />
      ))}
    </div>
  );

  if (error) return <ErrorState message={error} onRetry={loadAll} />;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Overview</h1>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5 mb-8">
        <StatCard label="Conversations Today"      value={stats.conversations_today} />
        <StatCard label="Conversations This Week"  value={stats.conversations_week} />
        <StatCard label="Resolution Rate"          value={stats.resolution_rate} unit="%" highlight />
        <StatCard label="Avg Turns / Conversation" value={stats.avg_turns} />
        <StatCard label="Open Tickets"             value={stats.open_tickets} highlight={stats.open_tickets > 0} />
      </div>

      <div className="flex items-baseline gap-3 mb-3">
        <h2 className="text-base font-semibold">Live Message Feed</h2>
        <span className="text-xs text-muted-foreground">
          {lastRefresh ? `Updated ${timeAgo(lastRefresh.toISOString())} · refreshes every 10 s` : ""}
        </span>
      </div>

      <Card className={feedPulse ? "ring-2 ring-primary/20 transition-shadow" : "transition-shadow"}>
        {feed.length === 0 ? (
          <CardContent className="pt-6 text-center text-muted-foreground text-sm py-10">
            No messages yet.
          </CardContent>
        ) : (
          <CardContent className="p-0 divide-y">
            {feed.map((msg, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-3 hover:bg-muted/30 transition-colors">
                <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-[0.65rem] font-bold flex-shrink-0">
                  {String(msg.user_id).slice(-2)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 mb-0.5">
                    <span className="text-xs font-semibold">User {msg.user_id}</span>
                    <span className="text-xs text-muted-foreground/60">· {msg.session_id}</span>
                  </div>
                  <p className="text-sm text-muted-foreground truncate">{msg.content}</p>
                </div>
                <span className="text-xs text-muted-foreground whitespace-nowrap pt-0.5 flex-shrink-0">{timeAgo(msg.ts)}</span>
              </div>
            ))}
          </CardContent>
        )}
      </Card>
    </div>
  );
}
