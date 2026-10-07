"""Builds and serializes an A2A `Task`, using `a2a.types` directly
(verified against the installed `a2a-sdk==1.2.1` — see `agent_card.py`'s
module docstring for the same verification trail).

Task lifecycle (A2A's own `TaskState`, not invented):
`TASK_STATE_SUBMITTED -> TASK_STATE_WORKING -> TASK_STATE_COMPLETED`, or
`TASK_STATE_WORKING -> TASK_STATE_FAILED`. Every A2A endpoint in this
project (Research, Document, Analyst — Milestones 7/8) is synchronous (no
task store, no polling, no message broker — see ADR 009, "Why M7's A2A
task handling is synchronous") so a client only ever observes the *final*
state in the HTTP response; `submitted`/`working` are logged as transient
events (`a2a.task_started`) rather than being independently queryable,
the same simplification Milestone 3 made for its own document-processing
sub-steps (see ADR 005).

`build_generic_task`/`_build_artifact` are the one shared implementation
every agent's task-building goes through — `build_task` (the Research
Agent's own entry point, kept for Milestone 7 backward compatibility) is
a thin wrapper over it, not a second implementation.
"""

from __future__ import annotations

import uuid
from typing import Any

from a2a.types import Artifact, Message, Part, Role, Task, TaskStatus
from a2a.types import TaskState as TaskStateEnum
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value

from app.a2a.schemas import ResearchResult

RESEARCH_RESULT_ARTIFACT_NAME = "research_result"


def build_generic_task(
    *,
    request_text: str,
    status: str,
    artifact_name: str,
    payload: dict[str, Any] | None,
    error: str | None,
) -> Task:
    """Builds a `Task` for any agent: `status == "completed"` attaches an
    `Artifact` named `artifact_name` carrying `payload` (JSON-able data,
    e.g. a Document/Analyst result dict); any other status is
    `TASK_STATE_FAILED`, with `error` (if given) carried as the status
    message — never a fabricated success artifact."""
    task = Task(id=str(uuid.uuid4()), context_id=str(uuid.uuid4()))
    task.history.append(
        Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=request_text)])
    )

    if status == "completed":
        task.status.CopyFrom(TaskStatus(state=TaskStateEnum.TASK_STATE_COMPLETED))
        task.artifacts.append(_build_artifact(name=artifact_name, payload=payload or {}))
    else:
        task.status.CopyFrom(TaskStatus(state=TaskStateEnum.TASK_STATE_FAILED))
        if error:
            task.status.message.CopyFrom(
                Message(
                    message_id=str(uuid.uuid4()), role=Role.ROLE_AGENT, parts=[Part(text=error)]
                )
            )

    return task


def _build_artifact(*, name: str, payload: dict[str, Any]) -> Artifact:
    value = Value()
    ParseDict(payload, value)
    artifact = Artifact(artifact_id=str(uuid.uuid4()), name=name)
    artifact.parts.append(Part(data=value))
    return artifact


def build_task(*, question: str, result: ResearchResult) -> Task:
    """The Research Agent's own entry point (Milestone 7) — unchanged
    behavior, now implemented in terms of `build_generic_task`."""
    payload = {
        "answer": result.answer,
        "sources": [
            {
                "chunk_id": str(source.chunk_id),
                "document_id": str(source.document_id),
                "filename": source.filename,
                "page_number": source.page_number,
                "similarity": source.similarity,
            }
            for source in result.sources
        ],
        "token_usage": result.token_usage,
    }
    return build_generic_task(
        request_text=question,
        status=result.status,
        artifact_name=RESEARCH_RESULT_ARTIFACT_NAME,
        payload=payload,
        error=result.error,
    )


def task_to_dict(task: Task) -> dict:
    return MessageToDict(task, preserving_proto_field_name=False)
