import { Routes, Route, NavLink } from "react-router-dom";
import DashboardPage          from "./pages/DashboardPage";
import TicketsPage            from "./pages/TicketsPage";
import TicketDetailPage       from "./pages/TicketDetailPage";
import ConversationsPage      from "./pages/ConversationsPage";
import ConversationDetailPage from "./pages/ConversationDetailPage";
import AgentHealthPage        from "./pages/AgentHealthPage";

function NavItem({ to, end, children }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        isActive
          ? "text-white text-sm font-medium"
          : "text-slate-400 text-sm font-medium hover:text-white transition-colors"
      }
    >
      {children}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <nav className="bg-slate-900 text-white px-6 h-14 flex items-center gap-6 sticky top-0 z-40 shadow-sm">
        <span className="font-bold text-base tracking-tight mr-auto">Telegram Support</span>
        <NavItem to="/" end>Dashboard</NavItem>
        <NavItem to="/conversations">Conversations</NavItem>
        <NavItem to="/tickets">Tickets</NavItem>
        <NavItem to="/health">Health</NavItem>
      </nav>
      <main className="max-w-6xl mx-auto px-4 py-8">
        <Routes>
          <Route path="/"                         element={<DashboardPage />} />
          <Route path="/conversations"            element={<ConversationsPage />} />
          <Route path="/conversations/:sessionId" element={<ConversationDetailPage />} />
          <Route path="/tickets"                  element={<TicketsPage />} />
          <Route path="/tickets/:id"              element={<TicketDetailPage />} />
          <Route path="/health"                   element={<AgentHealthPage />} />
        </Routes>
      </main>
    </div>
  );
}
