"""The multi-agent workflow under REAL authentication.

The orchestrator calls the Research/Document/Analyst task endpoints over HTTP
(routed here through the same ASGI app). Those endpoints are authenticated
like every other route, so the caller's bearer token must be forwarded to
them — otherwise the workflow would break (and no temporary public exemption
exists to hide that). Key set and identity tables are in-memory fakes.
"""

from __future__ import annotations

import pytest

from ...auth_fixtures import FakeIdentityRepository, SigningKey, mint_token

RUN = "/api/v1/multi-agent/run"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("message", "expected_agents"),
    [
        ("What is 15% of 500?", ["analyst"]),
        ("What does our travel policy say about hotel reimbursement?", ["research"]),
    ],
)
async def test_the_callers_identity_reaches_every_specialist_agent(
    auth_env,
    orchestrator_env,
    async_client,
    signing_key: SigningKey,
    identity_repo: FakeIdentityRepository,
    message: str,
    expected_agents: list[str],
) -> None:
    identity_repo.link()

    response = await async_client.post(
        RUN, json={"message": message}, headers=_bearer(mint_token(signing_key))
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert [a["agent_name"] for a in payload["agents_used"]] == expected_agents
    assert all(a["status"] == "completed" for a in payload["agents_used"])
    # One identity check for the caller's request plus one per specialist call:
    # proof the token was forwarded and each hop authenticated it.
    assert identity_repo.lookups >= 2


async def test_an_anonymous_call_never_reaches_the_orchestrator(
    auth_env, orchestrator_env, async_client, identity_repo: FakeIdentityRepository
) -> None:
    response = await async_client.post(RUN, json={"message": "What is 15% of 500?"})

    assert response.status_code == 401
    assert identity_repo.lookups == 0


async def test_an_unlinked_identity_cannot_start_a_workflow(
    auth_env, orchestrator_env, async_client, signing_key: SigningKey
) -> None:
    response = await async_client.post(
        RUN, json={"message": "What is 15% of 500?"}, headers=_bearer(mint_token(signing_key))
    )

    assert response.status_code == 403


async def test_the_specialist_task_endpoints_reject_direct_anonymous_calls(
    auth_env, orchestrator_env, async_client
) -> None:
    for path, body in (
        ("/api/v1/agents/research/tasks", {"question": "q"}),
        ("/api/v1/agents/analyst/tasks", {"question": "q"}),
        (
            "/api/v1/agents/document/tasks",
            {"document_ids": ["00000000-0000-0000-0000-000000000001"]},
        ),
    ):
        response = await async_client.post(path, json=body)

        assert response.status_code == 401, path


async def test_the_agent_cards_stay_public(auth_env, orchestrator_env, async_client) -> None:
    for path in (
        "/.well-known/agent-card.json",
        "/api/v1/agents/research/card",
        "/api/v1/agents/document/card",
        "/api/v1/agents/analyst/card",
    ):
        response = await async_client.get(path)

        assert response.status_code == 200, path
