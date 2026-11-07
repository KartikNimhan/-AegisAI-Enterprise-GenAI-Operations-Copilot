"""Claim-level evidence evaluation (M10.7): offline only, never used to label production answers.

Today a citation proves only that the cited source was retrieved (ADR 017, D-5). Before any
answer may say a source *supports* a claim, a checker has to be measured on labelled claims and
shown to be reliable enough. This module provides the pieces for that measurement:

- a loader for a labelled claim set (`supported`, `unsupported`, `conflicting`);
- `LexicalSupportChecker`, a deterministic baseline (word overlap, numbers, negation). It makes no
  model call and needs no network; it exists to give the evaluation a floor, not to ship;
- metrics that put the dangerous error first: a claim wrongly called supported;
- `SupportLabelGate`, the proposed release criteria. It cannot pass without the owner's explicit
  approval (`owner_approved`), and nothing in the application reads it: the citation API keeps
  returning `support: "not_verified"`.

Nothing here is imported by request-serving code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Label = Literal["supported", "unsupported", "conflicting"]
LABELS: tuple[Label, ...] = ("supported", "unsupported", "conflicting")


class EvidenceDatasetError(ValueError):
    """A structurally invalid claim set (unknown passage, duplicate id, unknown label)."""


@dataclass(frozen=True)
class EvidenceCase:
    id: str
    claim: str
    passage_id: str
    label: Label
    note: str


@dataclass(frozen=True)
class EvidenceDataset:
    version: int
    description: str
    passages: dict[str, str]
    cases: tuple[EvidenceCase, ...]


def load_evidence_dataset(path: Path) -> EvidenceDataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    passages = {str(key): str(value) for key, value in raw["passages"].items()}
    seen: set[str] = set()
    cases: list[EvidenceCase] = []
    for item in raw["cases"]:
        case_id = str(item["id"])
        if case_id in seen:
            raise EvidenceDatasetError(f"duplicate case id {case_id!r}")
        seen.add(case_id)
        if item["passage_id"] not in passages:
            raise EvidenceDatasetError(f"case {case_id!r} names an unknown passage")
        if item["label"] not in LABELS:
            raise EvidenceDatasetError(f"case {case_id!r} has an unknown label")
        cases.append(
            EvidenceCase(
                id=case_id,
                claim=str(item["claim"]),
                passage_id=str(item["passage_id"]),
                label=item["label"],
                note=str(item.get("note", "")),
            )
        )
    if not cases:
        raise EvidenceDatasetError("the dataset has no cases")
    return EvidenceDataset(
        version=int(raw["version"]),
        description=str(raw["description"]),
        passages=passages,
        cases=tuple(cases),
    )


# -- the lexical baseline ---------------------------------------------------------------

_WORD = re.compile(r"[a-z]+|\d+(?:[.,]\d+)?")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NEGATIONS = frozenset({"not", "no", "never", "cannot", "without", "nor", "none", "neither"})
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
        "there",
        "which",
        "who",
        "whom",
        "what",
        "when",
        "where",
        "how",
        "than",
        "then",
        "so",
        "such",
        "may",
        "can",
        "must",
        "should",
        "will",
        "would",
        "shall",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "per",
        "each",
        "any",
        "all",
    ]
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ies", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _terms(text: str) -> set[str]:
    words = _WORD.findall(text.lower().replace("n't", " not"))
    return {_stem(w) for w in words if w not in _STOPWORDS and w not in _NEGATIONS}


def _negated(text: str) -> bool:
    words = _WORD.findall(text.lower().replace("n't", " not"))
    return sum(w in _NEGATIONS for w in words) % 2 == 1


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


@dataclass(frozen=True)
class SupportVerdict:
    supported: bool
    overlap: float
    reason: str


@dataclass(frozen=True)
class LexicalSupportChecker:
    """Calls a claim supported when one sentence of the passage covers enough of its content words,
    has every number the claim states, and agrees with it on negation.

    A deliberately simple floor: it cannot see paraphrase, swapped roles ("A pays B" vs "B pays A")
    or most contradictions that keep the same words. The evaluation report shows where it fails.
    """

    min_overlap: float = 0.75

    def check(self, claim: str, passage: str) -> SupportVerdict:
        claim_terms = _terms(claim)
        if not claim_terms:
            return SupportVerdict(False, 0.0, "the claim has no content words")
        claim_numbers = _numbers(claim)
        best = SupportVerdict(False, 0.0, "no sentence of the passage matches")
        for sentence in _SENTENCE.split(passage):
            overlap = len(claim_terms & _terms(sentence)) / len(claim_terms)
            if overlap < best.overlap:
                continue
            if overlap < self.min_overlap:
                best = SupportVerdict(False, overlap, "too few of the claim's words")
            elif not claim_numbers <= _numbers(sentence):
                best = SupportVerdict(False, overlap, "a number in the claim is not in the passage")
            elif _negated(claim) != _negated(sentence):
                best = SupportVerdict(
                    False, overlap, "the claim and the passage differ in negation"
                )
            else:
                return SupportVerdict(True, overlap, "covered by one sentence")
        return best


# -- metrics ----------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    case: EvidenceCase
    verdict: SupportVerdict

    @property
    def correct(self) -> bool:
        return self.verdict.supported == (self.case.label == "supported")


@dataclass(frozen=True)
class EvidenceReport:
    dataset_version: int
    checker: str
    results: tuple[CaseResult, ...]
    counts: dict[str, int] = field(default_factory=dict)

    def _count(self, *, label: Label | None = None, predicted: bool | None = None) -> int:
        return sum(
            1
            for r in self.results
            if (label is None or r.case.label == label)
            and (predicted is None or r.verdict.supported == predicted)
        )

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def accuracy(self) -> float:
        return sum(r.correct for r in self.results) / self.total

    @property
    def supported_precision(self) -> float | None:
        """Of the claims the checker called supported, how many really were. `None` if it called
        none supported (undefined, not 1.0)."""
        predicted = self._count(predicted=True)
        return (
            None if predicted == 0 else self._count(label="supported", predicted=True) / predicted
        )

    @property
    def supported_recall(self) -> float | None:
        actual = self._count(label="supported")
        return None if actual == 0 else self._count(label="supported", predicted=True) / actual

    def false_supported_rate(self, label: Label) -> float | None:
        """Of the claims with this (not supported) label, how many were wrongly called supported."""
        actual = self._count(label=label)
        return None if actual == 0 else self._count(label=label, predicted=True) / actual

    def errors(self) -> list[CaseResult]:
        return [r for r in self.results if not r.correct]


def evaluate(
    dataset: EvidenceDataset, checker: LexicalSupportChecker | None = None
) -> EvidenceReport:
    checker = checker or LexicalSupportChecker()
    results = tuple(
        CaseResult(case, checker.check(case.claim, dataset.passages[case.passage_id]))
        for case in dataset.cases
    )
    counts = {label: sum(1 for c in dataset.cases if c.label == label) for label in LABELS}
    return EvidenceReport(
        dataset_version=dataset.version,
        checker=f"lexical(min_overlap={checker.min_overlap})",
        results=results,
        counts=counts,
    )


# -- the release gate ---------------------------------------------------------------------


@dataclass(frozen=True)
class SupportLabelGate:
    """PROPOSED criteria for ever showing "Supported" (M10 decision 6). Not agreed yet: the
    owner decides D-5 and these numbers. `owner_approved` stays False until then, so the gate
    cannot pass, whatever a report says."""

    min_cases: int = 300
    min_cases_per_label: int = 100
    min_supported_precision: float = 0.95
    max_false_supported_conflicting: float = 0.02
    max_false_supported_unsupported: float = 0.05
    owner_approved: bool = False

    def failures(self, report: EvidenceReport) -> list[str]:
        problems: list[str] = []
        if not self.owner_approved:
            problems.append("the owner has not approved these criteria or a checker (D-5)")
        if report.total < self.min_cases:
            problems.append(f"{report.total} cases, fewer than {self.min_cases}")
        for label in LABELS:
            if report.counts.get(label, 0) < self.min_cases_per_label:
                problems.append(
                    f"{report.counts.get(label, 0)} {label} cases, "
                    f"fewer than {self.min_cases_per_label}"
                )
        precision = report.supported_precision
        if precision is None or precision < self.min_supported_precision:
            problems.append(
                f"supported precision {_fmt(precision)} < {self.min_supported_precision}"
            )
        for label, limit in (
            ("conflicting", self.max_false_supported_conflicting),
            ("unsupported", self.max_false_supported_unsupported),
        ):
            rate = report.false_supported_rate(label)  # type: ignore[arg-type]
            if rate is None or rate > limit:
                problems.append(f"false 'supported' on {label} {_fmt(rate)} > {limit}")
        return problems

    def passes(self, report: EvidenceReport) -> bool:
        return not self.failures(report)


def _fmt(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"


def format_report(report: EvidenceReport, gate: SupportLabelGate | None = None) -> str:
    gate = gate or SupportLabelGate()
    lines = [
        f"Evidence evaluation: dataset v{report.dataset_version}, checker {report.checker}",
        f"Cases: {report.total} ({', '.join(f'{k} {v}' for k, v in report.counts.items())})",
        f"Accuracy: {report.accuracy:.3f}",
        f"Supported precision: {_fmt(report.supported_precision)}",
        f"Supported recall: {_fmt(report.supported_recall)}",
        f"False 'supported' on unsupported: {_fmt(report.false_supported_rate('unsupported'))}",
        f"False 'supported' on conflicting: {_fmt(report.false_supported_rate('conflicting'))}",
        "",
        "Errors:",
    ]
    lines += [
        f"  {r.case.id} [{r.case.label}] predicted "
        f"{'supported' if r.verdict.supported else 'not supported'} "
        f"(overlap {r.verdict.overlap:.2f}; {r.verdict.reason})"
        for r in report.errors()
    ] or ["  none"]
    lines += ["", "Support label gate: " + ("PASS" if gate.passes(report) else "FAIL")]
    lines += [f"  - {problem}" for problem in gate.failures(report)]
    return "\n".join(lines)


def split_claims(answer: str, source_ids: Iterable[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Splits an answer into sentences that carry citation markers, with the ids they cite (only
    ids in `source_ids`). The unit a future checker would judge; sentences without a marker are
    not claims about a source."""
    known = set(source_ids)
    claims: list[tuple[str, tuple[str, ...]]] = []
    for sentence in _SENTENCE.split(answer.strip()):
        cited = tuple(
            dict.fromkeys(
                sid
                for group in re.findall(r"\[(S\d{1,3}(?:\s*,\s*S\d{1,3})*)\]", sentence)
                for sid in re.split(r"\s*,\s*", group)
                if sid in known
            )
        )
        if cited:
            text = re.sub(r"\s*\[S\d{1,3}(?:\s*,\s*S\d{1,3})*\]", "", sentence).strip()
            claims.append((text, cited))
    return claims


__all__: Sequence[str] = (
    "EvidenceCase",
    "EvidenceDataset",
    "EvidenceDatasetError",
    "EvidenceReport",
    "LexicalSupportChecker",
    "SupportLabelGate",
    "SupportVerdict",
    "evaluate",
    "format_report",
    "load_evidence_dataset",
    "split_claims",
)
