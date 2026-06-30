import { Routes, Route, NavLink } from "react-router-dom";
import TicketsPage from "./pages/TicketsPage";
import TicketDetailPage from "./pages/TicketDetailPage";

export default function App() {
  return (
    <div className="app">
      <nav className="navbar">
        <span className="navbar-brand">Telegram Support</span>
        <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
          Tickets
        </NavLink>
      </nav>
      <main className="container">
        <Routes>
          <Route path="/" element={<TicketsPage />} />
          <Route path="/tickets/:id" element={<TicketDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
