"""Minimal HTTP client for the AegisAI backend, used by the Streamlit UI."""

import os
from typing import Any

import httpx

BACKEND_URL = os.environ.get("AEGIS_BACKEND_URL", "http://localhost:8000")


def check_backend_readiness(timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    """Calls the backend's readiness endpoint and returns (status_code, body)."""
    response = httpx.get(f"{BACKEND_URL}/health/ready", timeout=timeout)
    return response.status_code, response.json()
