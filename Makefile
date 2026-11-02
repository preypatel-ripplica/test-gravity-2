.PHONY: start-backend start-frontend setup setup-backend setup-frontend

# Backend: FastAPI on http://localhost:8000 (future: https://api.xyz)
# --reload watches Python + .env so code and config changes pick up automatically
start-backend:
	PYTHONPATH=. .venv/bin/uvicorn backend.main.app:app --reload \
		--reload-include '*.py' \
		--reload-include '.env' \
		--reload-include 'backend/.env' \
		--host 127.0.0.1 --port 8000

# Frontend: React (Vite) on http://localhost:5173 (future: https://app.xyz)
# Vite HMR is enabled by default via npm run dev
start-frontend:
	cd frontend && npm run dev

setup: setup-backend setup-frontend

setup-backend:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -r backend/main/requirements.txt

setup-frontend:
	cd frontend && npm install
