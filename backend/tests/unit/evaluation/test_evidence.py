"""M10.7: the offline claim-level evidence evaluation (dataset, baseline checker, metrics, gate).

The recorded figures are the MEASURED result of the lexical baseline on the small synthetic set;
they are pinned so any change to the checker or the set is visible. They are not evidence that any
answer is correct, and nothing in the application uses them.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation.evidence import (
    EvidenceDatasetError,
    LexicalSupportChecker,
    SupportLabelGate,
    evaluate,
    format_report,
    load_evidence_dataset,
    split_claims,
)

BACKEND = Path(__file__).resolve().parents[3]
DATASET = BACKEND / "tests" / "evaluation" / "data" / "evidence_eval_dataset.json"


@pytest.fixture(scope="module")
def report():
    return evaluate(load_evidence_dataset(DATASET))


def test_the_dataset_says_it_is_synthetic_and_covers_every_label() -> None:
    dataset = load_evidence_dataset(DATASET)
    assert "SYNTHETIC" in dataset.description
    assert {case.label for case in dataset.cases} == {"supported", "unsupported", "conflicting"}
    assert len({case.id for case in dataset.cases}) == len(dataset.cases) == 42


def test_the_measured_baseline_result_is_recorded(report) -> None:
    assert report.counts == {"supported": 18, "unsupported": 11, "conflicting": 13}
    assert sum(r.correct for r in report.results) == 35
    assert report.supported_precision == pytest.approx(15 / 19)
    assert report.supported_recall == pytest.approx(15 / 18)
    assert report.false_supported_rate("unsupported") == pytest.approx(1 / 11)
    assert report.false_supported_rate("conflicting") == pytest.approx(3 / 13)
    assert sorted(r.case.id for r in report.errors()) == ["d4", "d6", "e7", "l3", "r2", "r4", "t3"]


def test_the_gate_fails_today_on_every_criterion(report) -> None:
    failures = SupportLabelGate().failures(report)
    assert any("owner has not approved" in f for f in failures)
    assert any("fewer than 300" in f for f in failures)
    assert any("supported precision" in f for f in failures)
    assert not SupportLabelGate().passes(report)
    assert "Support label gate: FAIL" in format_report(report)


def test_the_gate_cannot_pass_without_owner_approval_even_on_a_perfect_report(report) -> None:
    perfect = replace(
        report,
        results=tuple(
            replace(r, verdict=replace(r.verdict, supported=r.case.label == "supported"))
            for r in report.results
        ),
    )
    assert perfect.accuracy == 1.0
    lenient = SupportLabelGate(min_cases=1, min_cases_per_label=1)
    assert lenient.failures(perfect) == [
        "the owner has not approved these criteria or a checker (D-5)"
    ]
    assert SupportLabelGate(min_cases=1, min_cases_per_label=1, owner_approved=True).passes(perfect)


def test_undefined_precision_is_not_reported_as_perfect(report) -> None:
    none_supported = replace(
        report,
        results=tuple(
            replace(r, verdict=replace(r.verdict, supported=False)) for r in report.results
        ),
    )
    assert none_supported.supported_precision is None
    assert any("undefined" in f for f in SupportLabelGate().failures(none_supported))


@pytest.mark.parametrize(
    ("claim", "passage", "supported"),
    [
        ("Backups are kept for 35 days.", "Backups are kept for 35 days.", True),
        ("Backups are kept for 30 days.", "Backups are kept for 35 days.", False),
        ("Alcohol is reimbursable.", "Alcohol is not reimbursable.", False),
        ("Alcohol isn't reimbursable.", "Alcohol is not reimbursable.", True),
        ("Taxis are free.", "Backups are kept for 35 days.", False),
        ("The.", "Anything at all.", False),
    ],
)
def test_the_baseline_checker(claim: str, passage: str, supported: bool) -> None:
    assert LexicalSupportChecker().check(claim, passage).supported is supported


def test_a_claim_is_judged_against_one_sentence_not_words_spread_over_the_passage() -> None:
    passage = "Support tickets are deleted after two years. Customer records are kept seven years."
    assert (
        not LexicalSupportChecker()
        .check("Support tickets are kept seven years.", passage)
        .supported
    )


def test_split_claims_keeps_only_cited_sentences_and_known_ids() -> None:
    answer = "Hotels are capped at 180 euros [S1]. Receipts take 30 days [S2, S9]. No source here."
    assert split_claims(answer, ["S1", "S2"]) == [
        ("Hotels are capped at 180 euros.", ("S1",)),
        ("Receipts take 30 days.", ("S2",)),
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["cases"].append(dict(raw["cases"][0])),
        lambda raw: raw["cases"][0].update(passage_id="nowhere"),
        lambda raw: raw["cases"][0].update(label="probably"),
        lambda raw: raw.update(cases=[]),
    ],
)
def test_an_invalid_dataset_is_rejected(tmp_path: Path, mutate) -> None:
    raw = json.loads(DATASET.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(EvidenceDatasetError):
        load_evidence_dataset(path)


def test_no_request_serving_code_imports_the_evidence_module() -> None:
    """Decision 6: nothing may label an answer "Supported" from this evaluation."""
    importers = []
    for path in (BACKEND / "app").rglob("*.py"):
        if path.parent.name == "evaluation":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            if any(name.startswith("app.evaluation.evidence") for name in names):
                importers.append(str(path))
    assert importers == []


def test_the_citation_api_still_only_says_not_verified() -> None:
    from app.api.schemas.citations import AvailableCitation, MessageCitationSummary

    for model in (AvailableCitation, MessageCitationSummary):
        assert model.model_fields["support"].annotation.__args__ == ("not_verified",)  # type: ignore[union-attr]
