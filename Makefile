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
# Vite 8 needs Node ^20.19 or >=22.12; prefer Homebrew node@22 when installed.
start-frontend:
	@if [ -x /opt/homebrew/opt/node@22/bin/node ]; then \
		PATH="/opt/homebrew/opt/node@22/bin:$$PATH" cd frontend && npm run dev; \
	else \
		cd frontend && npm run dev; \
	fi

setup: setup-backend setup-frontend

setup-backend:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -r backend/main/requirements.txt

setup-frontend:
	cd frontend && npm install
