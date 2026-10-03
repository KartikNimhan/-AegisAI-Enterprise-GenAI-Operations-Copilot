"""Document ingestion: validation, extraction, normalization, and chunking.

Provider/format-specific logic stays isolated in `extractors/` (one module
per `DocumentType`) and `chunking/` (one module per chunking strategy).
`app.services.document_service.DocumentService` is the only orchestrator —
nothing here talks to the database or the HTTP layer.
"""
