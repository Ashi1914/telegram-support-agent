import axios from "axios";

const api = axios.create({ baseURL: "/api" });

export const fetchTickets = (status) =>
  api.get("/tickets", { params: status ? { status } : {} }).then((r) => r.data);

export const fetchTicket = (id) =>
  api.get(`/tickets/${id}`).then((r) => r.data);

export const updateTicketStatus = (id, status) =>
  api.patch(`/tickets/${id}/status`, { status }).then((r) => r.data);

export const fetchDashboardStats = () =>
  api.get("/dashboard/stats").then((r) => r.data);

export const fetchDashboardFeed = () =>
  api.get("/dashboard/feed").then((r) => r.data);

export const fetchConversations = () =>
  api.get("/conversations").then((r) => r.data);

export const fetchConversation = (sessionId) =>
  api.get(`/conversations/${encodeURIComponent(sessionId)}`).then((r) => r.data);

export const fetchHealthTools  = () => api.get("/health/tools").then((r) => r.data);
export const fetchHealthLlm    = () => api.get("/health/llm").then((r) => r.data);
export const fetchHealthTokens = () => api.get("/health/tokens").then((r) => r.data);
export const fetchHealthErrors = () => api.get("/health/errors").then((r) => r.data);
