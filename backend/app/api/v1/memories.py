"""Agent-memory endpoints: the user's own notes, which they can list, add, edit and delete.

Kept thin: rules live in `app.memory.service.AgentMemoryService`. Every operation is scoped to the
caller (a memory that is not theirs is a 404), and each change is audited without its content.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.schemas.memories import (
    MemoryClearResponse,
    MemoryCreateRequest,
    MemoryResponse,
    MemoryUpdateRequest,
)
from app.core import audit
from app.core.exceptions import AppError
from app.core.security import PrincipalDep
from app.domain.enums.memory_kind import MemorySource
from app.memory.exceptions import MemoryLimitError, MemoryValidationError
from app.memory.service import MemoryServiceDep

router = APIRouter(prefix="/memories", tags=["memories"])


def _refused(exc: MemoryValidationError | MemoryLimitError) -> AppError:
    if isinstance(exc, MemoryLimitError):
        return AppError(str(exc), status_code=status.HTTP_409_CONFLICT, code="memory_full")
    return AppError(
        str(exc), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, code="memory_invalid"
    )


@router.get("", response_model=list[MemoryResponse])
async def list_memories(memory: MemoryServiceDep) -> list[MemoryResponse]:
    return [MemoryResponse.model_validate(m) for m in await memory.list_all()]


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: MemoryCreateRequest, memory: MemoryServiceDep, principal: PrincipalDep
) -> MemoryResponse:
    try:
        saved, _created = await memory.remember(
            request.content, kind=request.kind, source=MemorySource.USER
        )
    except (MemoryValidationError, MemoryLimitError) as exc:
        raise _refused(exc) from exc
    audit.record("memory.saved", actor=principal, resource_type="memory", resource_id=saved.id)
    return MemoryResponse.model_validate(saved)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID,
    request: MemoryUpdateRequest,
    memory: MemoryServiceDep,
    principal: PrincipalDep,
) -> MemoryResponse:
    try:
        updated = await memory.update(memory_id, request.content)
    except MemoryValidationError as exc:
        raise _refused(exc) from exc
    audit.record(
        "memory.updated",
        actor=principal,
        resource_type="memory",
        resource_id=memory_id,
        outcome="success" if updated is not None else "not_found",
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return MemoryResponse.model_validate(updated)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, memory: MemoryServiceDep, principal: PrincipalDep
) -> None:
    deleted = await memory.delete(memory_id)
    audit.record(
        "memory.deleted",
        actor=principal,
        resource_type="memory",
        resource_id=memory_id,
        outcome="success" if deleted else "not_found",
    )
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")


@router.delete("", response_model=MemoryClearResponse)
async def clear_memories(memory: MemoryServiceDep, principal: PrincipalDep) -> MemoryClearResponse:
    """Forget everything the agent remembers about the caller."""
    count = await memory.clear()
    audit.record("memory.cleared", actor=principal, resource_type="memory", deleted=count)
    return MemoryClearResponse(deleted=count)
