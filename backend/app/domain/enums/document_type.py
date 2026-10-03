"""The document types this milestone can extract text from.

Deliberately not user-extensible at the enum level — adding a new type
means adding a new extractor (see `app.documents.extractors`) and a new
member here together. `Settings.document_allowed_types` can *restrict*
which of these are currently accepted by the API without a code change,
but cannot widen beyond what the code actually supports.
"""

from enum import StrEnum


class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MARKDOWN = "markdown"
