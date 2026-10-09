.PHONY: install run run-frontend test test-unit test-integration test-frontend lint format typecheck check migrate migrate-create docker-build docker-up docker-down docker-restart docker-logs docker-migrate docker-shell docker-shell-frontend docker-config k8s-validate

install:
	uv sync --all-groups

run:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run-frontend:
	cd frontend/streamlit && uv run --group frontend streamlit run app.py

test:
	uv run pytest

test-unit:
	uv run pytest backend/tests/unit

test-integration:
	uv run pytest -m integration backend/tests/integration

test-frontend:
	uv run --group frontend pytest frontend/streamlit/tests -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run --all-groups pyright

check: lint typecheck test test-frontend

migrate:
	cd backend && uv run alembic upgrade head

migrate-create:
	cd backend && uv run alembic revision --autogenerate -m "$(name)"

docker-build:
	docker compose build

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-restart:
	docker compose restart

docker-logs:
	docker compose logs -f

# Runs the existing Alembic migrations once, against the Compose Postgres
# — the one-off `migrate` service (profile "tools"), never started by
# `docker-up`. See docker-compose.yml's own comment on that service.
docker-migrate:
	docker compose run --rm migrate

docker-shell:
	docker compose exec backend /bin/sh

docker-shell-frontend:
	docker compose exec frontend /bin/sh

# Pure syntax/structure validation of docker-compose.yml — does not
# require the Docker daemon to be running (docker compose config only
# parses/merges the YAML).
docker-config:
	docker compose config

# Client-side structural validation of the Kubernetes manifests. Does not
# require a reachable cluster — see
# infra/kubernetes/validate_manifests.py's own docstring for why a live
# `kubectl apply --dry-run=client` isn't used here.
k8s-validate:
	uv run python infra/kubernetes/validate_manifests.py
