"""A small, synthetic, non-sensitive evaluation corpus for RAG retrieval.

Not a test module itself (no `test_*` functions). Deliberately tiny (three
documents, six chunks, five questions) and topically well-separated —
this is an illustrative Recall@K fixture to prove the retrieval pipeline
works end to end, not a benchmark dataset; see
docs/architecture/decisions/007-rag-pipeline.md, "Evaluation approach",
for why no benchmark score is claimed from it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalChunk:
    document_title: str
    text: str


@dataclass(frozen=True)
class EvalQuestion:
    question: str
    relevant_chunk_texts: tuple[str, ...]


TRAVEL_EXPENSE_REIMBURSEMENT = (
    "Employees may claim reimbursement for business travel expenses including "
    "flights, hotels, and meals when accompanied by itemized receipts."
)
TRAVEL_EXPENSE_DEADLINE = (
    "Expense reports must be submitted within 30 days of the trip's "
    "completion to be eligible for reimbursement."
)
SECURITY_MFA = (
    "All employees must enable multi-factor authentication on their "
    "corporate accounts within the first week of employment."
)
SECURITY_PASSWORD_ROTATION = (
    "Passwords must be at least twelve characters long and rotated every ninety days."
)
REMOTE_WORK_AVAILABILITY = (
    "Employees working remotely must maintain a stable internet connection "
    "and be reachable during core business hours."
)
REMOTE_WORK_STIPEND = "The company provides a one-time stipend of $500 to set up a home office."

EVAL_CORPUS: list[EvalChunk] = [
    EvalChunk("Travel & Expense Policy", TRAVEL_EXPENSE_REIMBURSEMENT),
    EvalChunk("Travel & Expense Policy", TRAVEL_EXPENSE_DEADLINE),
    EvalChunk("IT Security Policy", SECURITY_MFA),
    EvalChunk("IT Security Policy", SECURITY_PASSWORD_ROTATION),
    EvalChunk("Remote Work Policy", REMOTE_WORK_AVAILABILITY),
    EvalChunk("Remote Work Policy", REMOTE_WORK_STIPEND),
]

EVAL_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion("How do I get reimbursed for a business trip?", (TRAVEL_EXPENSE_REIMBURSEMENT,)),
    EvalQuestion(
        "What's the deadline for submitting an expense report?", (TRAVEL_EXPENSE_DEADLINE,)
    ),
    EvalQuestion("Do I need two-factor authentication on my work account?", (SECURITY_MFA,)),
    EvalQuestion("How often do I need to change my password?", (SECURITY_PASSWORD_ROTATION,)),
    EvalQuestion("Does the company help pay for home office equipment?", (REMOTE_WORK_STIPEND,)),
]
