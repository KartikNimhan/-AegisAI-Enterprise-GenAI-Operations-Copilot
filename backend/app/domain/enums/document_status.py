"""The lifecycle of a document processing attempt.

Kept to four coarse states rather than one per pipeline sub-step
(extraction/normalization/chunking/persistence) — see
docs/architecture/decisions/005-document-ingestion.md for why: this
milestone processes synchronously within a single request, so those
sub-steps never exist as independently observable, queryable states; a
finer-grained enum would add schema surface with no operational value
until processing actually moves to a background worker.
"""

from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
