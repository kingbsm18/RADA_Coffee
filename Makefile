COMPOSE=docker compose -f deploy/docker-compose.dev.yml --env-file .env

.PHONY: dev down test lint

dev:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check .
