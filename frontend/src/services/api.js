import axios from "axios";

const api = axios.create({ baseURL: "/api" });

export const fetchTickets = (status) =>
  api.get("/tickets", { params: status ? { status } : {} }).then((r) => r.data);

export const fetchTicket = (id) =>
  api.get(`/tickets/${id}`).then((r) => r.data);

export const updateTicketStatus = (id, status) =>
  api.patch(`/tickets/${id}/status`, { status }).then((r) => r.data);
