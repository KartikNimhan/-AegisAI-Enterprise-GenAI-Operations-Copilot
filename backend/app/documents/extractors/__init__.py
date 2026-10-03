"""Text extractors, one per `DocumentType`.

Each format's parsing library is isolated to its own module — nothing
outside `extractors/` imports `pypdf` or `docx` directly.
"""

from app.documents.extractors.base import DocumentExtractor, ExtractionResult
from app.documents.extractors.docx import DocxExtractor
from app.documents.extractors.markdown import MarkdownExtractor
from app.documents.extractors.pdf import PdfExtractor
from app.documents.extractors.text import PlainTextExtractor
from app.domain.enums.document_type import DocumentType

EXTRACTORS: dict[DocumentType, DocumentExtractor] = {
    DocumentType.PDF: PdfExtractor(),
    DocumentType.DOCX: DocxExtractor(),
    DocumentType.TXT: PlainTextExtractor(),
    DocumentType.MARKDOWN: MarkdownExtractor(),
}


def get_extractor(document_type: DocumentType) -> DocumentExtractor:
    return EXTRACTORS[document_type]


__all__ = [
    "DocumentExtractor",
    "ExtractionResult",
    "get_extractor",
]
