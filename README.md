# Plug AI

## Setup

Copy the example env into place and fill in your values:

```bash
cp backend/.env.example backend/.env
```

Set at least:

- `MONGODB_URI` / `MONGODB_DB_NAME`
- `SECRET_KEY`
- `BEACON_SUPERUSER_EMAIL` / `BEACON_SUPERUSER_PASSWORD` (admin login)

Optional: OpenAI, Google OAuth, and R2 (`STORAGE_PROVIDER=r2` + `R2_*`) for media uploads.

The Vite dev server proxies API calls to port `8000`. You usually do not need a frontend `.env` locally (only set `VITE_API_URL` if the API is not on localhost:8000).

## Run locally

From this project root (the folder that contains `backend/` and `frontend/`):

```bash
# API
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/main/requirements.txt
PYTHONPATH=. uvicorn backend.main.app:app --reload --port 8000 --host 127.0.0.1

# Frontend (second terminal, same project root)
cd frontend
npm install
npm run dev
```

- App: http://localhost:5173  
- API docs: http://localhost:8000/docs  

Sign in with the superuser email/password from `backend/.env`.
