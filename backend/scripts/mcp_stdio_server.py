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

Requires a reachable Postgres (the same `DATABASE_URL` the API uses) since
`search_knowledge_base`/`get_document_metadata` query real tables through
the same `RetrievalService`/`DocumentRepository` the API uses — this is
not a fake/demo server.
"""

from __future__ import annotations

import asyncio

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
    async with AsyncSessionLocal() as session:
        documents = DocumentRepository(session)
        embedding_service = EmbeddingService(
            session=session,
            settings=settings,
            provider=get_local_embedding_provider(),
            documents=documents,
            chunks=DocumentChunkRepository(session),
            embeddings=ChunkEmbeddingRepository(session),
        )
        strategy = VectorRetrievalStrategy(
            embedding_service=embedding_service, repository=RetrievalRepository(session)
        )
        retrieval = RetrievalService(strategy=strategy, settings=settings)

        server = build_mcp_server(documents=documents, retrieval=retrieval)
        await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
