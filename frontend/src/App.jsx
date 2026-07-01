import { Routes, Route, NavLink } from "react-router-dom";
import DashboardPage          from "./pages/DashboardPage";
import TicketsPage            from "./pages/TicketsPage";
import TicketDetailPage       from "./pages/TicketDetailPage";
import ConversationsPage      from "./pages/ConversationsPage";
import ConversationDetailPage from "./pages/ConversationDetailPage";

export default function App() {
  return (
    <div className="app">
      <nav className="navbar">
        <span className="navbar-brand">Telegram Support</span>
        <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
          Dashboard
        </NavLink>
        <NavLink to="/conversations" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
          Conversations
        </NavLink>
        <NavLink to="/tickets" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
          Tickets
        </NavLink>
      </nav>
      <main className="container">
        <Routes>
          <Route path="/"                                element={<DashboardPage />} />
          <Route path="/conversations"                   element={<ConversationsPage />} />
          <Route path="/conversations/:sessionId"        element={<ConversationDetailPage />} />
          <Route path="/tickets"                         element={<TicketsPage />} />
          <Route path="/tickets/:id"                     element={<TicketDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
