"""Exercise the production atomic lifecycle on the ignored internal PRDs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import forge.mcp.server as server
from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
)
from forge.rubric.models import FieldSpec
from forge.service import prepare_assessment


ROOT = Path(__file__).resolve().parents[1]
FORGE_DIR = ROOT / "sampleDoc/.forge"
RUN_PATHS = [
    FORGE_DIR / f"evaluation-atomic-run{run_index}.json"
    for run_index in (1, 2, 3)
]
SOURCES = {
    "micro_dramas": ROOT / "sampleDoc/Micro Dramas.docx",
    "rush_playback_quality_selection_guide": (
        ROOT / "sampleDoc/Rush_Playback_Quality_Selection_Guide.docx"
    ),
}


def _empty_extraction(prepared) -> dict[str, object]:
    return {
        "criteria": [
            {
                "criterion_id": criterion.id,
                "fields": [
                    {"name": field.name, "value": None, "evidence": None}
                    for field in criterion.fields
                ],
            }
            for criterion in prepared.rubric.criteria
        ]
    }


def _evaluation_batch(case_id: str) -> CriterionEvaluationBatch:
    runs = []
    for path in RUN_PATHS:
        payload = json.loads(path.read_text())
        case = payload["cases"][case_id]
        runs.append(
            CriterionEvaluationRun(
                run_index=payload["run_index"],
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id=case["batch_id"],
                        plan_fingerprint=case["plan_fingerprint"],
                        criteria=[item["submission"] for item in case["items"]],
                    )
                ],
            )
        )
    return CriterionEvaluationBatch(runs=runs)


def _answer_text(criterion_id: str, field_name: str, sequence: int) -> str:
    return (
        f"Forge production exercise decision {sequence} for {criterion_id}.{field_name}: "
        "the named owner will implement the explicit behavior, measure a 30% target "
        "within 90 days, review it by 2026-12-31, retain audit data for 30 days, "
        "meet WCAG keyboard and screen-reader accessibility, and monitor a named "
        "metric dashboard, log, alert, on-call, and support signal in version 1 draft."
    )


def _field_value(field: FieldSpec, answer: str):
    values = {
        "number": 30,
        "boolean": True,
        "date": "2026-12-31",
        "string[]": [answer],
    }
    return values.get(field.type, answer)


def _delta_for_pending(state, plan) -> tuple[str, list[dict[str, str]]]:
    rubric = server.load_rubric(state.rubric_name)
    pending_by_criterion: dict[str, list] = {}
    targets: list[dict[str, str]] = []
    for pending in state.pending_answers:
        pending_by_criterion.setdefault(pending.answer.criterion_id, []).append(pending)
        if pending.target_field is not None:
            targets.append(
                {
                    "answer_id": pending.answer_id,
                    "criterion_id": pending.answer.criterion_id,
                    "field_name": pending.target_field,
                    "answer": pending.answer.answer,
                }
            )
    criteria = []
    for criterion_id, pending_items in pending_by_criterion.items():
        criterion = rubric.criterion(criterion_id)
        by_field = {
            item.target_field: item
            for item in pending_items
            if item.target_field is not None
        }
        fields = []
        for field in criterion.fields:
            pending = by_field.get(field.name)
            fields.append(
                {
                    "name": field.name,
                    "value": (
                        _field_value(field, pending.answer.answer)
                        if pending is not None
                        else None
                    ),
                    "evidence": (
                        {"quote": pending.answer.answer}
                        if pending is not None
                        else None
                    ),
                }
            )
        criteria.append({"criterion_id": criterion.id, "fields": fields})
    return (
        json.dumps(
            {"delta_fingerprint": plan.delta_fingerprint, "criteria": criteria}
        ),
        targets,
    )


def _final_extraction(prepared, targets: list[dict[str, str]]) -> str:
    by_target: dict[tuple[str, str], list[str]] = {}
    for item in targets:
        by_target.setdefault(
            (item["criterion_id"], item["field_name"]), []
        ).append(item["answer"])
    criteria = []
    for criterion in prepared.rubric.criteria:
        fields = []
        for field in criterion.fields:
            answers = by_target.get((criterion.id, field.name), [])
            value = (
                answers
                if len(answers) > 1
                else _field_value(field, answers[0])
                if answers
                else None
            )
            fields.append(
                {
                    "name": field.name,
                    "value": value,
                    "evidence": {"quote": answers[0]} if answers else None,
                }
            )
        criteria.append({"criterion_id": criterion.id, "fields": fields})
    run = {"criteria": criteria}
    return json.dumps({"runs": [run, run, run]})


def _run_case(case_id: str, source: Path, output_dir: Path) -> dict[str, object]:
    started_at = time.monotonic()
    print(f"[{case_id}] preparing source", file=sys.stderr, flush=True)
    prepared = prepare_assessment(str(source))
    empty_run = _empty_extraction(prepared)
    extraction_json = json.dumps({"runs": [empty_run, empty_run, empty_run]})
    evaluation_json = _evaluation_batch(case_id).model_dump(mode="json")
    start_request = {
        "source_path": str(source),
        "extraction_json": extraction_json,
        "question_mode": "atomic_assertion",
        "evaluation_json": evaluation_json,
        "framing": "opportunity_bet" if case_id == "micro_dramas" else None,
        "start_new": True,
        "operation_id": f"exercise-start-{case_id}",
    }
    response = server.start_prd_review(**start_request)
    print(f"[{case_id}] review started", file=sys.stderr, flush=True)
    replayed_start = server.start_prd_review(**start_request)
    if replayed_start.review_session_id != response.review_session_id:
        raise RuntimeError("start review replay created a different session")
    initial_band = response.turn.state.assessment.band
    review_id = response.review_session_id
    session_version = response.session_version
    question_count = 0
    atomic_questions = 0
    legacy_questions = 0
    transport_retries = 1
    credited_answers = 0
    uncredited_answers = 0
    attempted_issue_ids: set[str] = set()
    answer_targets: list[dict[str, str]] = []

    while True:
        session = server._reviews_store().get(review_id)
        turn = server.current_turn(session.state)
        question = turn.next_question
        if question is None:
            if turn.checkpoint_due:
                pass
            else:
                break
        else:
            question_count += 1
            if question_count == 1 or question_count % 10 == 0:
                print(
                    f"[{case_id}] question {question_count}: "
                    f"{question.question_kind} {question.criterion_id}.{question.target_field}",
                    file=sys.stderr,
                    flush=True,
                )
            atomic = question.question_kind == "atomic_assertion"
            atomic_questions += int(atomic)
            legacy_questions += int(not atomic)
            attempted_issue_ids.update(question.issue_ids)
            answer = _answer_text(
                question.criterion_id,
                question.target_field or "decision",
                question_count,
            )
            operation_id = f"exercise-answer-{case_id}-{question_count}"
            answer_request = {
                "review_session_id": review_id,
                "session_version": session_version,
                "operation_id": operation_id,
                "answer": answer,
                "question_id": question.question_id if atomic else None,
                "evaluation_revision": (
                    question.evaluation_revision if atomic else None
                ),
            }
            recorded = server.record_prd_answer(**answer_request)
            replayed = server.record_prd_answer(**answer_request)
            transport_retries += 1
            if replayed.session_version != recorded.session_version:
                raise RuntimeError("answer replay changed the session version")
            session_version = recorded.session_version
            if not recorded.turn.checkpoint_due:
                continue

        prepared_checkpoint = server.prepare_prd_checkpoint(
            review_id,
            session_version,
            f"exercise-prepare-{case_id}-{question_count}",
        )
        session_version = prepared_checkpoint.session_version
        pending_state = server._reviews_store().get(review_id).state
        delta_json, targets = _delta_for_pending(
            pending_state, prepared_checkpoint.plan
        )
        answer_targets.extend(targets)
        checkpoint = server.apply_prd_checkpoint(
            review_id,
            session_version,
            f"exercise-apply-{case_id}-{question_count}",
            delta_json,
        )
        credited_answers += len(checkpoint.result.credited_answer_ids)
        uncredited_answers += len(checkpoint.result.uncredited_answer_ids)
        session_version = checkpoint.session_version

    preview = server.preview_prd_revision(
        review_id,
        session_version,
        f"exercise-preview-{case_id}",
    )
    session_version = preview.session_version
    actions = {
        edit.edit_id: "integrate" if edit.target_section is not None else "audit_only"
        for edit in preview.plan.edits
    }
    output_path = output_dir / f"{case_id}-atomic-revised.docx"
    written = server.write_integrated_prd_revision(
        review_id,
        session_version,
        f"exercise-write-{case_id}",
        str(output_path),
        preview.plan,
        actions,
    )
    session_version = written.session_version
    final_prepared = prepare_assessment(str(output_path))
    print(f"[{case_id}] revision written", file=sys.stderr, flush=True)
    final_extraction = _final_extraction(final_prepared, answer_targets)
    completed = server.complete_prd_review(
        review_id,
        session_version,
        f"exercise-complete-{case_id}",
        final_extraction,
    )
    final_state = server._reviews_store().get(review_id).state
    resolved_issue_ids = {
        issue_id
        for resolution in final_state.atomic_resolutions
        for issue_id in resolution.issue_ids
    }
    elapsed_ms = round((time.monotonic() - started_at) * 1000, 2)
    return {
        "case_id": case_id,
        "source": str(source.relative_to(ROOT)),
        "review_session_id": review_id,
        "workflow_state": completed.workflow_state.value,
        "initial_band": initial_band,
        "final_band": completed.assessment.assessment.band,
        "questions": question_count,
        "atomic_questions": atomic_questions,
        "legacy_fallback_questions": legacy_questions,
        "legacy_fallback_rate": round(
            legacy_questions / question_count if question_count else 0.0, 4
        ),
        "credited_answers": credited_answers,
        "uncredited_answers": uncredited_answers,
        "answer_closure_rate": round(
            credited_answers / (credited_answers + uncredited_answers)
            if credited_answers + uncredited_answers
            else 0.0,
            4,
        ),
        "attempted_issue_ids": len(attempted_issue_ids),
        "resolved_issue_ids": len(resolved_issue_ids),
        "issue_closure_rate": round(
            len(resolved_issue_ids) / len(attempted_issue_ids)
            if attempted_issue_ids
            else 0.0,
            4,
        ),
        "transport_retries": transport_retries,
        "delta_extractions": final_state.delta_extraction_count,
        "delta_input_characters": final_state.delta_input_characters,
        "verified_answers": len(final_state.verified_answers),
        "output": str(output_path.relative_to(ROOT)),
        "elapsed_ms": elapsed_ms,
    }


def run(
    case_ids: list[str] | None = None,
    output_dir: Path | None = None,
) -> dict[str, object]:
    output_dir = (output_dir or FORGE_DIR / "production-exercise").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = case_ids or list(SOURCES)
    with tempfile.TemporaryDirectory(prefix="forge-atomic-production-") as temporary:
        os.environ["FORGE_SESSION_DB"] = str(Path(temporary) / "reviews.sqlite3")
        server._review_repository = None
        cases = [
            _run_case(case_id, SOURCES[case_id], output_dir)
            for case_id in selected
        ]
    return {
        "artifact_type": "forge.atomic_production_exercise.v1",
        "authority": "owner_approved_synthetic",
        "calibration_eligible": False,
        "score_effect": "none",
        "provider_calls": 0,
        "token_usage": {
            "available": False,
            "reason": (
                "Deterministic exercise reused frozen verified evaluations and "
                "performed no provider inference."
            ),
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--case", action="append", choices=sorted(SOURCES))
    args = parser.parse_args()
    payload = run(args.case, args.artifact_dir)
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
