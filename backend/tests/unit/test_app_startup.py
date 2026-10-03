"""Tests that the FastAPI application assembles and starts correctly."""

from fastapi.testclient import TestClient

from app.main import app, create_app


def test_create_app_returns_fastapi_instance() -> None:
    application = create_app()
    assert application.title == "AegisAI"


def test_openapi_schema_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "AegisAI"


def test_docs_endpoint_is_available(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200


def test_app_module_exposes_app_instance() -> None:
    assert app is not None
