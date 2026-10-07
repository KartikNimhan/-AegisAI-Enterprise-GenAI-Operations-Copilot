"""Multi-agent orchestration (Milestone 8): one `MultiAgentOrchestrator`
routes a user request to up to three specialized agents — Research
(Milestone 7), Document, and Analyst (new this milestone) — reached only
through the existing A2A boundary (`app.a2a.client.A2AClient`), never by
importing a specialized agent's service class directly. See
docs/architecture/decisions/010-multi-agent-architecture.md.

`models.py` (typed context/result/workflow dataclasses), `capabilities.py`
(the static agent/capability registry), `router.py` (the deterministic
routing policy), `policies.py` (allowed workflow transitions and loop/
depth limits), `aggregation.py` (`ResultAggregator`), `orchestrator.py`
(`MultiAgentOrchestrator`), `exceptions.py` (typed failure modes).
"""
