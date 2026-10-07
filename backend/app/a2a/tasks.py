"""Builds and serializes the A2A `Task` representing one Research Agent
run, using `a2a.types` directly (verified against the installed
`a2a-sdk==1.2.1` — see `agent_card.py`'s module docstring for the same
verification trail).

Task lifecycle (A2A's own `TaskState`, not invented):
`TASK_STATE_SUBMITTED -> TASK_STATE_WORKING -> TASK_STATE_COMPLETED`, or
`TASK_STATE_WORKING -> TASK_STATE_FAILED`. This milestone's Research Agent
endpoint is synchronous (no task store, no polling, no message broker —
see ADR 009, "Why M7's A2A task handling is synchronous") so a client only
ever observes the *final* state in the HTTP response; `submitted`/`working`
are logged as transient events (`a2a.task_started`) rather than being
independently queryable, the same simplification Milestone 3 made for its
document-processing sub-steps (see ADR 005).
"""

from __future__ import annotations

import uuid

from a2a.types import Artifact, Message, Part, Role, Task, TaskStatus
from a2a.types import TaskState as TaskStateEnum
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value

from app.a2a.schemas import ResearchResult

RESEARCH_RESULT_ARTIFACT_NAME = "research_result"


def build_task(*, question: str, result: ResearchResult) -> Task:
    task = Task(id=str(uuid.uuid4()), context_id=str(uuid.uuid4()))
    task.history.append(
        Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=question)])
    )

    if result.status == "completed":
        task.status.CopyFrom(TaskStatus(state=TaskStateEnum.TASK_STATE_COMPLETED))
        task.artifacts.append(_build_result_artifact(result))
    else:
        task.status.CopyFrom(TaskStatus(state=TaskStateEnum.TASK_STATE_FAILED))
        if result.error:
            task.status.message.CopyFrom(
                Message(
                    message_id=str(uuid.uuid4()),
                    role=Role.ROLE_AGENT,
                    parts=[Part(text=result.error)],
                )
            )

    return task


def _build_result_artifact(result: ResearchResult) -> Artifact:
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
    }
    value = Value()
    ParseDict(payload, value)
    artifact = Artifact(artifact_id=str(uuid.uuid4()), name=RESEARCH_RESULT_ARTIFACT_NAME)
    artifact.parts.append(Part(data=value))
    return artifact


def task_to_dict(task: Task) -> dict:
    return MessageToDict(task, preserving_proto_field_name=False)
