# Telegram Customer Support AI Agent

A customer support bot powered by Claude AI, with a React dashboard for managing tickets.

## Stack
- **Backend**: FastAPI, SQLAlchemy (async), SQLite
- **Frontend**: React + Vite
- **AI**: Anthropic Claude

## Quick Start

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
cp .env.example .env       # fill in your keys
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Project Structure
```
├── backend/
│   └── app/
│       ├── api/          # Route handlers (webhook, tickets)
│       ├── core/         # Config / settings
│       ├── db/           # SQLAlchemy models & session
│       ├── models/       # Pydantic schemas
│       └── services/     # AI & Telegram API clients
└── frontend/
    └── src/
        ├── pages/        # TicketsPage, TicketDetailPage
        └── services/     # Axios API calls
```
