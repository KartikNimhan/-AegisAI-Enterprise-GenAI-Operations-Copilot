"""An uploaded DOCX cannot make the server read local files through XML external entities (XXE).

A DOCX is a zip of XML parts. If the parser resolved external entities, a document declaring
`<!ENTITY x SYSTEM "file:///etc/passwd">` would have that file's contents extracted, chunked,
embedded and shown back to the uploader. python-docx parses with `resolve_entities=False`; this
test pins that behavior with a real, crafted document.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import docx

from app.documents.extractors.docx import DocxExtractor

PROBE_TEXT = "LOCAL-FILE-CONTENT-MUST-NOT-LEAK"


def crafted_docx(entity_target: str) -> bytes:
    buffer = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("MARKER")
    document.save(buffer)
    source = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
    xml = source.read("word/document.xml").decode()
    # Replace whatever XML declaration python-docx wrote (it uses single quotes) with one that
    # declares the external entity, and reference the entity in the paragraph text.
    declaration = re.match(r"<\?xml[^>]*\?>", xml)
    assert declaration, "no XML declaration to replace"
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        f'<!DOCTYPE d [<!ENTITY xxe SYSTEM "{entity_target}">]>' + xml[declaration.end() :]
    )
    assert "<!DOCTYPE" in xml
    xml = xml.replace("MARKER", "MARKER &xxe; END", 1)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in source.namelist():
            archive.writestr(name, xml if name == "word/document.xml" else source.read(name))
    return out.getvalue()


def probe_target(tmp_path: Path) -> str:
    probe_file = tmp_path / "probe.txt"
    probe_file.write_text(PROBE_TEXT, encoding="utf-8")
    return probe_file.resolve().as_uri()


def test_the_crafted_document_really_is_an_xxe_payload(tmp_path: Path) -> None:
    # Control: a parser that DOES resolve entities reads the local file from this exact document.
    # Without this, the test below could pass because the payload was simply broken.
    from lxml import etree  # type: ignore[attr-defined]  # lxml ships no type stubs

    content = crafted_docx(probe_target(tmp_path))
    xml = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml")
    unsafe = etree.XMLParser(resolve_entities=True, no_network=True)

    assert PROBE_TEXT in etree.tostring(etree.fromstring(xml, unsafe), encoding="unicode")


def test_an_external_entity_is_never_resolved(tmp_path: Path) -> None:
    text = DocxExtractor().extract(crafted_docx(probe_target(tmp_path))).text

    assert "MARKER" in text  # the document itself was read
    assert PROBE_TEXT not in text  # but the local file was not
