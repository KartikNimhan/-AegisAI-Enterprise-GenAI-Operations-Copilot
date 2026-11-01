"""The multi-agent workflow's final answer passes the output guard (AIGSEC-015), through the real
endpoint with a scripted model (see conftest.py). The fake credential is assembled at runtime."""

from __future__ import annotations

from app.llm.schemas import CompletionResponse, TokenUsage

from ..rag.doubles import ScriptedRAGGateway

SECRET = "gsk" + "_" + "Ab3" * 12


async def test_a_direct_multi_agent_answer_is_redacted(async_client, orchestrator_env) -> None:
    orchestrator_env["gateway"] = ScriptedRAGGateway(
        completion=CompletionResponse(
            content=f"Sure: {SECRET}", model="m", provider="test", usage=TokenUsage()
        )
    )

    response = await async_client.post("/api/v1/multi-agent/run", json={"message": "hello"})

    assert response.status_code == 200
    assert SECRET not in response.text
    assert response.json()["answer"] == "Sure: [REDACTED:credential]"
