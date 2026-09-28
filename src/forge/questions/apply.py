from __future__ import annotations

import hashlib
import json
import re

from pydantic import ValidationError

from forge.questions.models import (
    PreparedQuestionGeneration,
    QuestionGenerationSubmission,
    ShadowQuestion,
)


_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[._/%+-][A-Za-z0-9]+)*")
_QUOTED = re.compile(r'["“”]([^"“”]+)["“”]')
_SAFE_WORDS = {
    "a", "about", "and", "answer", "apply", "are", "as", "at", "be",
    "before", "between", "can", "clarify", "decide", "define", "do", "does",
    "expected", "for", "from", "how", "if", "implement", "in", "is", "must",
    "need", "needs", "of", "on", "or", "outcome", "prd", "precedence", "requirement",
    "requirements", "resolve", "rule", "rules", "should", "take", "team", "than",
    "that", "the", "these", "this", "those", "to", "under", "versus", "what", "when",
    "where", "which", "who", "why", "will", "with",
}


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _evidence_ids(
    prepared: PreparedQuestionGeneration, issue_id: str
) -> list[str]:
    target = prepared.target
    issue = next(item for item in target.issues if item.issue_id == issue_id)
    subject_ids = [target.subject.evidence.evidence_id] if target.subject else []
    return sorted(set(issue.evidence_ids + subject_ids))


def _fallback(
    prepared: PreparedQuestionGeneration, reason: str, issue_id: str | None = None
) -> ShadowQuestion:
    target = prepared.target
    selected = next(
        (item for item in target.issues if item.issue_id == issue_id),
        target.issues[0],
    )
    identity = {
        "plan_id": target.plan_id,
        "issue_id": selected.issue_id,
        "question": target.fallback_question,
        "generation_mode": "rubric_fallback",
    }
    return ShadowQuestion(
        question_id=_hash(identity),
        plan_id=target.plan_id,
        criterion_id=target.criterion_id,
        assertion_id=target.assertion_id,
        status=target.status,
        issue_id=selected.issue_id,
        evidence_ids=_evidence_ids(prepared, selected.issue_id),
        question=target.fallback_question,
        answer_contract=target.answer_contract,
        generation_mode="rubric_fallback",
        rejection_reason=reason,
    )


def render_deterministic_question(
    prepared: PreparedQuestionGeneration,
) -> ShadowQuestion:
    """Render the verified rubric/evidence template without a model completion."""
    target = prepared.target
    selected = target.issues[0]
    identity = {
        "plan_id": target.plan_id,
        "issue_id": selected.issue_id,
        "question": target.fallback_question,
        "generation_mode": "deterministic_template",
    }
    return ShadowQuestion(
        question_id=_hash(identity),
        plan_id=target.plan_id,
        criterion_id=target.criterion_id,
        assertion_id=target.assertion_id,
        status=target.status,
        issue_id=selected.issue_id,
        evidence_ids=_evidence_ids(prepared, selected.issue_id),
        question=target.fallback_question,
        answer_contract=target.answer_contract,
        generation_mode="deterministic_template",
    )


def _wording_is_grounded(
    prepared: PreparedQuestionGeneration,
    submission: QuestionGenerationSubmission,
) -> bool:
    question = submission.question.strip()
    if "\n" in question or question.count("?") != 1 or not question.endswith("?"):
        return False
    target = prepared.target
    issue = next(item for item in target.issues if item.issue_id == submission.issue_id)
    evidence_by_id = {item.evidence_id: item for item in target.evidence}
    evidence_text = " ".join(
        evidence_by_id[evidence_id].exact_quote for evidence_id in issue.evidence_ids
    )
    if target.subject is not None:
        evidence_text = " ".join(
            (evidence_text, target.subject.evidence.exact_quote)
        ).strip()
    trusted_text = " ".join(
        (
            target.assertion_id.replace("_", " "),
            target.assertion_description,
            target.answer_contract,
            evidence_text,
            " ".join(issue.missing_decisions),
        )
    )
    allowed = {token.casefold() for token in _TOKEN.findall(trusted_text)} | _SAFE_WORDS
    if any(token.casefold() not in allowed for token in _TOKEN.findall(question)):
        return False
    return all(quote in evidence_text for quote in _QUOTED.findall(question))


def apply_question_generation(
    prepared: PreparedQuestionGeneration, completion: str
) -> ShadowQuestion:
    """Validate generated wording or return the rubric-owned fallback."""
    try:
        payload = json.loads(completion)
    except (json.JSONDecodeError, TypeError):
        return _fallback(prepared, "invalid_json")
    try:
        submission = QuestionGenerationSubmission.model_validate(payload)
    except ValidationError:
        return _fallback(prepared, "invalid_submission")
    target = prepared.target
    if (
        submission.plan_id != target.plan_id
        or submission.issue_id not in target.issue_ids
    ):
        return _fallback(prepared, "invalid_submission")
    if not _wording_is_grounded(prepared, submission):
        return _fallback(prepared, "unsupported_wording", submission.issue_id)

    issue = next(
        item for item in target.issues if item.issue_id == submission.issue_id
    )
    question = submission.question.strip()
    identity = {
        "plan_id": target.plan_id,
        "issue_id": issue.issue_id,
        "question": question,
        "generation_mode": "generated",
    }
    return ShadowQuestion(
        question_id=_hash(identity),
        plan_id=target.plan_id,
        criterion_id=target.criterion_id,
        assertion_id=target.assertion_id,
        status=target.status,
        issue_id=issue.issue_id,
        evidence_ids=_evidence_ids(prepared, issue.issue_id),
        question=question,
        answer_contract=target.answer_contract,
        generation_mode="generated",
    )
