.PHONY: qdrant api web test-api

qdrant:
	docker compose up -d

api:
	cd apps/api && . .venv/bin/activate && uvicorn app.main:app --reload --reload-dir app --port 8000

web:
	cd apps/web && npm run dev

test-api:
	cd apps/api && . .venv/bin/activate && pytest -q
