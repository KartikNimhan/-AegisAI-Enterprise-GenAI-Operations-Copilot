"""Helper for server-sent-event endpoints.

Once a `StreamingResponse` starts, its HTTP status and headers are committed. An error raised
by the generator after that point (an unknown or foreign `conversation_id`, for instance)
cannot become a 404: the framework logs an unhandled exception and the client receives a
"successful" 200 with an empty body. `start_stream` therefore runs the generator up to its
first event BEFORE the response is created, so anything that fails while the request is being
set up takes the normal error handlers, exactly as on the non-streaming twin of the endpoint.

Failures after the first event are still reported inside the stream (the endpoints emit a
terminal error event for those), as before.
"""

from __future__ import annotations

from collections.abc import AsyncIterator


async def start_stream(events: AsyncIterator[str]) -> AsyncIterator[str]:
    iterator = events.__aiter__()
    try:
        first = await iterator.__anext__()
    except StopAsyncIteration:
        return _nothing()
    return _replay(first, iterator)


async def _replay(first: str, rest: AsyncIterator[str]) -> AsyncIterator[str]:
    yield first
    async for event in rest:
        yield event


async def _nothing() -> AsyncIterator[str]:
    return
    yield  # pragma: no cover - makes this an (empty) async generator
