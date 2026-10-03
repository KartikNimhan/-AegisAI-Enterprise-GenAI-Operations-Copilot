.PHONY: install run test test-unit test-integration lint format typecheck check migrate migrate-create docker-up docker-down docker-logs

install:
	uv sync --all-groups

run:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest

test-unit:
	uv run pytest backend/tests/unit

test-integration:
	uv run pytest -m integration backend/tests/integration

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck test

migrate:
	cd backend && uv run alembic upgrade head

migrate-create:
	cd backend && uv run alembic revision --autogenerate -m "$(name)"

docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
