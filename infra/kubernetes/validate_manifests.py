"""Client-side structural validation for infra/kubernetes/*.yaml.

Why this exists instead of `kubectl apply --dry-run=client` or
kubeconform/kubeval: `kubectl`'s own dry-run (even "client-side") still
contacts a live cluster to discover the API's OpenAPI schema/resource
kinds before it will validate anything — confirmed empirically (it fails
immediately with a connection error when no cluster is reachable, even
with `--validate=false`). kubeconform/kubeval would need installing a new
toolchain for exactly one validation step, which the brief explicitly
says to avoid. This script is the pragmatic middle ground: it doesn't
replace a real `kubectl apply --dry-run=client`/`kubeconform` run against
a reachable cluster (do that too, when one is available — see this
milestone's own report for what was/wasn't actually run), but it does
catch real mistakes (invalid YAML, a missing required field, an
accidentally-real-looking secret value) without any extra dependency
beyond PyYAML, already installed transitively.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

_MANIFEST_DIR = Path(__file__).resolve().parent

_REQUIRED_TOP_LEVEL = ("apiVersion", "kind", "metadata")

# A real secret value would never be this obviously a placeholder — these
# example/template files are expected (and required) to contain exactly
# these markers, never a value that looks like a real credential.
_PLACEHOLDER_MARKERS = ("REPLACE_ME", "REPLACE_WITH", "example")
_SECRET_KINDS = {"Secret"}


def _iter_manifest_files() -> list[Path]:
    return sorted(p for p in _MANIFEST_DIR.glob("*.yaml"))


def _validate_document(doc: dict[str, Any], *, source: Path) -> list[str]:
    errors: list[str] = []
    for key in _REQUIRED_TOP_LEVEL:
        if key not in doc:
            errors.append(f"{source.name}: missing required top-level key {key!r}")
    if "metadata" in doc and "name" not in doc.get("metadata", {}):
        errors.append(f"{source.name}: metadata.name is required")

    kind = doc.get("kind")
    if kind in _SECRET_KINDS:
        errors.extend(_validate_secret_is_a_safe_template(doc, source=source))
    return errors


def _validate_secret_is_a_safe_template(doc: dict[str, Any], *, source: Path) -> list[str]:
    """Every Secret manifest in this repo must be an obvious, non-functional
    template — never a real value that happens to be committed."""
    errors: list[str] = []
    if not source.name.endswith(".example.yaml"):
        errors.append(
            f"{source.name}: a Secret manifest must be named '*.example.yaml' "
            "(a real Secret is never committed to this repository)"
        )
    values = doc.get("stringData") or doc.get("data") or {}
    for field_name, value in values.items():
        if not any(marker in str(value) for marker in _PLACEHOLDER_MARKERS):
            errors.append(
                f"{source.name}: Secret field {field_name!r} does not look like a "
                "placeholder — refusing to treat this as a safe template"
            )
    # A base64-looking long opaque string is exactly what someone pasting
    # a real credential's encoded form would produce — guard against it
    # even though the fields above already use `stringData` (plaintext).
    raw_text = source.read_text(encoding="utf-8")
    if re.search(r"[A-Za-z0-9+/]{40,}={0,2}", raw_text):
        errors.append(
            f"{source.name}: contains a long base64-looking string — verify this "
            "is not an accidentally-real secret value"
        )
    return errors


def main() -> int:
    files = _iter_manifest_files()
    if not files:
        print("No manifests found under infra/kubernetes/.")
        return 1

    all_errors: list[str] = []
    checked = 0
    for path in files:
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            all_errors.append(f"{path.name}: invalid YAML — {exc}")
            continue
        for doc in documents:
            if doc is None:
                continue
            checked += 1
            all_errors.extend(_validate_document(doc, source=path))

    print(f"Checked {checked} document(s) across {len(files)} file(s).")
    if all_errors:
        print("\nFAILED:")
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print("All manifests parsed and passed structural checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
