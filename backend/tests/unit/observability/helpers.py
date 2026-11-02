"""Reading the exposition text back, the way a scraper would."""

from __future__ import annotations

from prometheus_client.parser import text_string_to_metric_families

from app.observability import metrics


def exposition() -> str:
    return metrics.render().decode("utf-8")


def samples(text: str | None = None) -> list[tuple[str, dict[str, str], float]]:
    out = []
    for family in text_string_to_metric_families(text if text is not None else exposition()):
        for sample in family.samples:
            out.append((sample.name, dict(sample.labels), sample.value))
    return out


def value(name: str, **labels: str) -> float:
    """The sample `name` whose labels include `labels` (summed if several match); 0 if none."""
    return sum(
        v
        for n, lab, v in samples()
        if n == name and all(lab.get(k) == x for k, x in labels.items())
    )


def label_values(name: str, label: str) -> set[str]:
    return {lab[label] for n, lab, _ in samples() if n == name and label in lab}
