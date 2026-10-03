"""Provider-neutral file storage abstraction.

`base.py` defines the interface; `local.py` is the only implementation in
this milestone (local filesystem, for development). Adding S3/Azure
Blob/GCS later means writing a new module implementing `DocumentStorage` —
no change to `DocumentService` or the API layer.
"""
