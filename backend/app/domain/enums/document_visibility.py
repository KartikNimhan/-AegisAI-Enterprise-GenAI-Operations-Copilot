"""Who, besides its owner, may see a document.

`private` (the default) means the owner only. `organization` means every active
member of the owner's organization may read it (list, view, search and cite it);
only the owner, or an administrator of that organization, may change or delete
it. Nothing is ever visible across organizations.
"""

from enum import StrEnum


class DocumentVisibility(StrEnum):
    PRIVATE = "private"
    ORGANIZATION = "organization"
