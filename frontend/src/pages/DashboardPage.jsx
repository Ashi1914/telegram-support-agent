import { useCallback, useEffect, useState } from "react";
import { fetchDashboardFeed, fetchDashboardStats } from "../services/api";

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
    <div className={`stat-card${highlight ? " stat-card--highlight" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats]           = useState(null);
  const [feed, setFeed]             = useState([]);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [loading, setLoading]       = useState(true);
  const [feedPulse, setFeedPulse]   = useState(false);

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

  useEffect(() => {
    Promise.all([fetchDashboardStats(), fetchDashboardFeed()])
      .then(([s, f]) => {
        setStats(s);
        setFeed(f);
        setLastRefresh(new Date());
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const id = setInterval(refreshFeed, FEED_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refreshFeed]);

  if (loading) return <p className="dash-loading">Loading dashboard…</p>;

  return (
    <div>
      <h1 className="dash-title">Overview</h1>

      {/* ── Stat cards ─────────────────────────────────────────────────── */}
      <div className="stat-grid">
        <StatCard label="Conversations Today"      value={stats.conversations_today} />
        <StatCard label="Conversations This Week"  value={stats.conversations_week} />
        <StatCard
          label="Resolution Rate"
          value={stats.resolution_rate}
          unit="%"
          highlight
        />
        <StatCard label="Avg Turns / Conversation" value={stats.avg_turns} />
        <StatCard
          label="Open Tickets"
          value={stats.open_tickets}
          highlight={stats.open_tickets > 0}
        />
      </div>

      {/* ── Live feed ──────────────────────────────────────────────────── */}
      <div className="feed-header">
        <h2 className="feed-title">Live Message Feed</h2>
        <span className="feed-meta-text">
          {lastRefresh
            ? `Updated ${timeAgo(lastRefresh.toISOString())} · refreshes every 10 s`
            : ""}
        </span>
      </div>

      <div className={`feed-list${feedPulse ? " feed-list--pulse" : ""}`}>
        {feed.length === 0 ? (
          <p className="feed-empty">No messages yet.</p>
        ) : (
          feed.map((msg, i) => (
            <div key={i} className="feed-item">
              <div className="feed-avatar">
                {String(msg.user_id).slice(-2)}
              </div>
              <div className="feed-content">
                <div className="feed-top">
                  <span className="feed-user">User {msg.user_id}</span>
                  <span className="feed-session">· {msg.session_id}</span>
                </div>
                <div className="feed-text">{msg.content}</div>
              </div>
              <div className="feed-time">{timeAgo(msg.ts)}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
