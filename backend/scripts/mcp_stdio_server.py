"""Runs the AegisAI MCP server over stdio — the transport a real external
MCP client (e.g. the MCP Inspector, or Claude Desktop's own MCP config)
would use to talk to this process, as opposed to the in-process
`Client(server)` transport `app.mcp.client` uses for the agent's own
MCP calls (see that module's docstring for why in-process is the right
choice there).

Run from the `backend/` directory (so `app` is importable):

    uv run python scripts/mcp_stdio_server.py

or point an MCP Inspector / client config at:

    uv run --directory backend python scripts/mcp_stdio_server.py

Whose data it serves must be chosen explicitly (see `scripts/stdio_scope.py`); with nothing set it
refuses to start:

    MCP_STDIO_USER_ID=<uuid> MCP_STDIO_ORGANIZATION_ID=<uuid>   # one user's data (preferred)
    MCP_STDIO_ALLOW_UNRESTRICTED=true                           # every organization's data

Requires a reachable Postgres (the same `DATABASE_URL` the API uses) since
`search_knowledge_base`/`get_document_metadata` query real tables through
the same `RetrievalService`/`DocumentRepository` the API uses — this is
not a fake/demo server.
"""

from __future__ import annotations

import asyncio
import os
import sys

from stdio_scope import StdioScopeError, resolve_stdio_scope

from app.config import get_settings
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.session import AsyncSessionLocal
from app.embeddings.providers.local import get_local_embedding_provider
from app.embeddings.service import EmbeddingService
from app.mcp.server import build_mcp_server
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.service import RetrievalService
from app.rag.retrieval.strategy import VectorRetrievalStrategy


async def main() -> None:
    settings = get_settings()
    # No signed-in caller exists here, so the scope comes from the operator and fails closed.
    scope = resolve_stdio_scope(os.environ)
    async with AsyncSessionLocal() as session:
        documents = DocumentRepository(session, scope)
        embedding_service = EmbeddingService(
            session=session,
            settings=settings,
            provider=get_local_embedding_provider(),
            documents=documents,
            chunks=DocumentChunkRepository(session, scope),
            embeddings=ChunkEmbeddingRepository(session, scope),
        )
        strategy = VectorRetrievalStrategy(
            embedding_service=embedding_service, repository=RetrievalRepository(session, scope)
        )
        retrieval = RetrievalService(strategy=strategy, settings=settings)

        server = build_mcp_server(documents=documents, retrieval=retrieval)
        await server.run_stdio_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except StdioScopeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from None
