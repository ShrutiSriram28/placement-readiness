from __future__ import annotations

from datetime import datetime, timezone

import httpx
import time
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.internet_tool import internet_tool
from app.llm_service import llm_service
from app.models import (
    AssessmentKind,
    AssessmentQuestion,
    AssessmentResponse,
    AssessmentSession,
    AssessmentStatus,
    EvidenceSource,
    QuestionResearch,
    QuestionType,
    ReadinessDimension,
    ReadinessEvidence,
)


MAX_GENERATION_ATTEMPTS = 3


def research_questions(db: Session, company: str, role: str) -> QuestionResearch:
    query = (f"{company} {role} " "interview coding aptitude " "technical questions " "frequently asked tagged topics")

    raw = internet_tool.search(query)

    sources = internet_tool.compact_results(raw)

    summary = llm_service.summarize_question_research(company, role, sources)

    record = QuestionResearch(
        company_name = company,
        role_name = role,
        query = query,
        sources = sources,
        recurring_topics = summary.recurring_topics,
        notable_question_titles = summary.notable_question_titles,
    )

    db.add(record)

    db.commit()

    db.refresh(record)

    return record


def latest_research(db: Session, company: str, role: str) -> QuestionResearch | None:
    return db.scalar(
        select(QuestionResearch)
        .where(
            QuestionResearch.company_name == company,
            QuestionResearch.role_name == role,
        )
        .order_by(QuestionResearch.created_at.desc())
    )


def ensure_research(db: Session, company: str, role: str) -> QuestionResearch:
    research = latest_research(db, company, role)

    if research is None:
        research = research_questions(db, company, role)

    return research


def get_previous_question_titles(db: Session, student_id: int, company: str, role: str, kind: AssessmentKind, limit: int = 50) -> list[str]:
    rows = db.execute(
        select(AssessmentQuestion.title)
        .join(
            AssessmentSession,
            AssessmentQuestion.session_id == AssessmentSession.id,
        )
        .where(
            AssessmentSession.student_id == student_id,
            AssessmentSession.company_name == company,
            AssessmentSession.role_name == role,
            AssessmentSession.kind == kind,
        )
        .order_by(AssessmentQuestion.id.desc())
        .limit(limit)
    ).all()

    return [row[0] for row in rows if row[0]]


def get_previous_question_prompts(db: Session, student_id: int, company: str, role: str, kind: AssessmentKind, limit: int = 20) -> list[str]:
    rows = db.execute(
        select(AssessmentQuestion.prompt)
        .join(
            AssessmentSession,
            AssessmentQuestion.session_id == AssessmentSession.id,
        )
        .where(
            AssessmentSession.student_id == student_id,
            AssessmentSession.company_name == company,
            AssessmentSession.role_name == role,
            AssessmentSession.kind == kind,
        )
        .order_by(AssessmentQuestion.id.desc())
        .limit(limit)
    ).all()

    return [row[0] for row in rows if row[0]]


def _runner_post(path: str, payload: dict, timeout: float = 12.0) -> dict:
    with httpx.Client(timeout = timeout) as client:
        response = client.post(
            (f"{settings.code_runner_url}" f"{path}"),
            json = payload,
        )

        response.raise_for_status()

        return response.json()


def _derive_expected_outputs(reference_solution: str, function_name: str, tests: list[dict]) -> list[dict]:
    result = _runner_post(
        "/derive",
        {
            "code": reference_solution,
            "function_name": function_name,
            "tests": tests,
        },
        timeout = 15.0,
    )

    if not result.get("ok"):
        raise ValueError(result.get("message") or ("Reference solution " "validation failed."))

    validated_tests = result.get("tests") or []

    if len(validated_tests) != len(tests):
        raise ValueError(("Runner returned an " "incomplete validated " "test set."))

    return validated_tests


def _coding_pack_is_semantically_valid(pack) -> tuple[bool, str]:
    validation = llm_service.validate_coding_questions(pack)

    if len(validation.validations) != len(pack.questions):
        return False, ("Coding validator " "returned the wrong " "number of validations.")

    invalid = [item for item in validation.validations if not item.valid]

    if invalid:
        return False, "; ".join((f"{item.title}: " f"{item.reason}") for item in invalid)

    return True, ""


def create_coding_assessment(db: Session, student_id: int, company: str, role: str, question_count: int = 3) -> AssessmentSession:
    research = ensure_research(db, company, role)

    previous_titles = get_previous_question_titles(
        db,
        student_id,
        company,
        role,
        AssessmentKind.CODING,
    )

    previous_prompts = get_previous_question_prompts(
        db,
        student_id,
        company,
        role,
        AssessmentKind.CODING,
    )

    last_error = "Unknown generation error."

    accepted_questions = None

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        try:
            pack = llm_service.generate_coding_questions(
                company,
                role,
                {
                    "recurring_topics": research.recurring_topics,
                    "notable_question_titles": research.notable_question_titles,
                    "sources": research.sources,
                },
                question_count,
                previous_titles = previous_titles,
                previous_prompts = previous_prompts,
            )

            if len(pack.questions) != question_count:
                raise ValueError(("Generator returned " f"{len(pack.questions)} " "questions; expected " f"{question_count}."))

            semantic_ok, semantic_error = _coding_pack_is_semantically_valid(pack)

            if not semantic_ok:
                raise ValueError(semantic_error)

            derived = []

            for item in pack.questions:
                raw_tests = [test.model_dump() for test in item.tests]

                if len(raw_tests) < 5:
                    raise ValueError((f"{item.title} " "has fewer than " "five tests."))

                validated_tests = _derive_expected_outputs(
                    item.reference_solution,
                    item.function_name,
                    raw_tests,
                )

                derived.append((item, validated_tests))

            accepted_questions = derived

            break

        except Exception as exc:
            last_error = f"attempt {attempt}: " f"{exc}"

            print(
                ("CODING GENERATION " "REJECTED: " f"{last_error}"),
                flush = True,
            )

    if accepted_questions is None:
        raise ValueError(
            (
                "Could not generate a "
                "fully validated coding "
                "assessment after "
                f"{MAX_GENERATION_ATTEMPTS} "
                "attempts. "
                "Last error: "
                f"{last_error}"
            )
        )

    session = AssessmentSession(
        student_id = student_id,
        kind = AssessmentKind.CODING,
        company_name = company,
        role_name = role,
    )

    db.add(session)

    db.flush()

    for index, (item, validated_tests) in enumerate(accepted_questions, start = 1):
        db.add(
            AssessmentQuestion(
                session_id = session.id,
                position = index,
                question_type = QuestionType.CODING,
                title = item.title,
                prompt = item.prompt,
                topic = item.topic,
                difficulty = item.difficulty,
                function_name = item.function_name,
                starter_code = item.starter_code,

                # These outputs were
                # generated by executing
                # the reference solution,
                # not by trusting the LLM.
                tests = validated_tests,
            )
        )

    db.commit()

    db.refresh(session)

    return session


def _validate_aptitude_pack(pack):
    print(
        ("APTITUDE: validating " f"{len(pack.questions)} candidate questions"),
        flush = True,
    )

    started_at = time.monotonic()

    validation_pack = llm_service.validate_aptitude_questions(pack)

    elapsed = time.monotonic() - started_at

    print(
        ("APTITUDE: validator returned " f"{len(validation_pack.validations)} results " f"in {elapsed:.1f}s"),
        flush = True,
    )

    if len(validation_pack.validations) != len(pack.questions):
        return [], [("Aptitude validator " "returned the wrong " "number of validations.")]

    accepted = []
    rejected = []

    for generated, validated in zip(pack.questions, validation_pack.validations):
        if validated.title != generated.title:
            rejected.append((f"{generated.title}: " "validator output " "title/order mismatch."))
            continue

        if not validated.valid:
            rejected.append((f"{generated.title}: " f"{validated.reason}"))
            continue

        if validated.confidence < 0.90:
            rejected.append((f"{generated.title}: " "validator confidence " f"{validated.confidence:.2f} " "was below 0.90."))
            continue

        if validated.correct_choice_index is None:
            rejected.append((f"{generated.title}: " "validator did not " "identify one correct " "answer."))
            continue

        if generated.correct_choice_index != validated.correct_choice_index:
            rejected.append(
                (
                    f"{generated.title}: "
                    "generator answer index "
                    f"{generated.correct_choice_index} "
                    "disagreed with "
                    "independent validator "
                    "index "
                    f"{validated.correct_choice_index}."
                )
            )
            continue

        accepted.append((generated, validated))

    return accepted, rejected


def create_aptitude_assessment(db: Session, student_id: int, company: str, role: str, question_count: int = 10) -> AssessmentSession:
    print(
        ("APTITUDE: start " f"student={student_id} " f"company={company} " f"role={role} " f"question_count={question_count}"),
        flush = True,
    )

    print(
        "APTITUDE: loading research",
        flush = True,
    )

    research_started_at = time.monotonic()

    research = ensure_research(db, company, role)

    print(
        ("APTITUDE: research loaded " f"in {time.monotonic() - research_started_at:.1f}s"),
        flush = True,
    )

    print(
        "APTITUDE: loading previous questions",
        flush = True,
    )

    previous_titles = get_previous_question_titles(
        db,
        student_id,
        company,
        role,
        AssessmentKind.APTITUDE,
    )

    previous_prompts = get_previous_question_prompts(
        db,
        student_id,
        company,
        role,
        AssessmentKind.APTITUDE,
    )

    print(
        ("APTITUDE: previous questions loaded " f"titles={len(previous_titles)} " f"prompts={len(previous_prompts)}"),
        flush = True,
    )

    accepted_questions = []
    rejection_reasons = []

    # Smaller batches are intentional. A local Ollama model can take a very
    # long time to generate and validate ten detailed questions in one call.
    # We keep valid questions and regenerate only the missing ones.
    generation_batch_size = 5
    max_rounds = max(4, (question_count + generation_batch_size - 1) // generation_batch_size + MAX_GENERATION_ATTEMPTS)

    round_number = 0

    while len(accepted_questions) < question_count and round_number < max_rounds:
        round_number += 1

        remaining = question_count - len(accepted_questions)

        batch_count = min(generation_batch_size, remaining)

        print(
            (
                "APTITUDE: generation round "
                f"{round_number}/{max_rounds}; "
                f"accepted={len(accepted_questions)}/"
                f"{question_count}; "
                f"requesting={batch_count}"
            ),
            flush = True,
        )

        generation_started_at = time.monotonic()

        try:
            pack = llm_service.generate_aptitude_questions(
                company,
                role,
                {
                    "recurring_topics": research.recurring_topics,
                    "notable_question_titles": research.notable_question_titles,
                },
                batch_count,
                previous_titles = previous_titles[-15:],
                previous_prompts = [prompt[:500] for prompt in previous_prompts[-8:]],
            )

        except Exception as exc:
            reason = "generator failed in " f"round {round_number}: " f"{exc}"

            rejection_reasons.append(reason)

            print(
                ("APTITUDE: " f"{reason}"),
                flush = True,
            )

            continue

        generation_elapsed = time.monotonic() - generation_started_at

        print(
            ("APTITUDE: generator returned " f"{len(pack.questions)} questions " f"in {generation_elapsed:.1f}s"),
            flush = True,
        )

        if not pack.questions:
            reason = f"round {round_number}: " "generator returned no questions."

            rejection_reasons.append(reason)

            print(
                ("APTITUDE: " f"{reason}"),
                flush = True,
            )

            continue

        # Add every generated candidate to the no-repeat context immediately,
        # even when validation rejects it. This prevents the next round from
        # producing the exact same bad question again.
        for generated in pack.questions:
            if generated.title:
                previous_titles.append(generated.title)

        try:
            validated_questions, rejected = _validate_aptitude_pack(pack)

        except Exception as exc:
            reason = "validator failed in " f"round {round_number}: " f"{exc}"

            rejection_reasons.append(reason)

            print(
                ("APTITUDE: " f"{reason}"),
                flush = True,
            )

            continue

        accepted_questions.extend(validated_questions)

        for generated, _validated in validated_questions:
            if generated.prompt:
                previous_prompts.append(generated.prompt)

        rejection_reasons.extend(rejected)

        print(
            (
                "APTITUDE: round complete; "
                f"accepted_this_round="
                f"{len(validated_questions)}, "
                f"rejected_this_round="
                f"{len(rejected)}, "
                f"total_accepted="
                f"{len(accepted_questions)}/"
                f"{question_count}"
            ),
            flush = True,
        )

        for reason in rejected:
            print(
                ("APTITUDE: rejected candidate: " f"{reason}"),
                flush = True,
            )

    if len(accepted_questions) < question_count:
        recent_errors = rejection_reasons[-5:]

        raise ValueError(
            (
                "Could not generate enough "
                "validated aptitude questions. "
                f"Accepted "
                f"{len(accepted_questions)}/"
                f"{question_count} after "
                f"{round_number} rounds. "
                "Recent rejection reasons: "
                + " | ".join(recent_errors)
            )
        )

    # In case a model unexpectedly returned extra candidates, persist only the
    # requested number.
    accepted_questions = accepted_questions[:question_count]

    print(
        ("APTITUDE: validation complete; " f"saving {len(accepted_questions)} questions"),
        flush = True,
    )

    session = AssessmentSession(
        student_id = student_id,
        kind = AssessmentKind.APTITUDE,
        company_name = company,
        role_name = role,
    )

    db.add(session)

    db.flush()

    for index, (generated, validated) in enumerate(accepted_questions, start = 1):
        db.add(
            AssessmentQuestion(
                session_id = session.id,
                position = index,
                question_type = QuestionType.MULTIPLE_CHOICE,
                title = generated.title,
                prompt = generated.prompt,
                topic = generated.topic,
                difficulty = generated.difficulty,
                choices = generated.choices,
                correct_choice_index = validated.correct_choice_index,
                explanation = validated.explanation,
            )
        )

    db.commit()

    db.refresh(session)

    print(
        ("APTITUDE: assessment saved " f"session_id={session.id}"),
        flush = True,
    )

    return session


def run_code(code: str, function_name: str, tests: list) -> dict:
    return _runner_post(
        "/run",
        {
            "code": code,
            "function_name": function_name,
            "tests": tests,
        },
        timeout = 12.0,
    )


def save_coding_response(db: Session, student_id: int, question: AssessmentQuestion, code: str) -> AssessmentResponse:
    if not question.function_name:
        raise ValueError(("Coding question is " "missing a function name."))

    if not question.tests:
        raise ValueError(("Coding question has no " "validated hidden tests."))

    result = run_code(code, question.function_name, question.tests)

    if not result.get("ok", False):
        raise ValueError(result.get("message") or ("Code execution " "failed."))

    total = int(result.get("total", 0))

    passed = int(result.get("passed", 0))

    if total <= 0:
        raise ValueError(("Code runner did not " "execute any tests."))

    score = passed / total * 100

    if passed == total:
        feedback = f"Passed all " f"{total} hidden tests."

    else:
        feedback = f"Passed " f"{passed}/{total} " "hidden tests."

    response = AssessmentResponse(
        question_id = question.id,
        student_id = student_id,
        response_text = code,
        score = round(score, 2),
        feedback = feedback,
    )

    db.add(response)

    db.commit()

    db.refresh(response)

    return response


def save_aptitude_response(db: Session, student_id: int, question: AssessmentQuestion, selected_index: int) -> AssessmentResponse:
    if question.correct_choice_index is None:
        raise ValueError(("This aptitude " "question does not " "have a validated " "answer key."))

    correct = selected_index == question.correct_choice_index

    response = AssessmentResponse(
        question_id = question.id,
        student_id = student_id,
        response_text = str(selected_index),
        score = 100 if correct else 0,
        feedback = question.explanation,
    )

    db.add(response)

    db.commit()

    db.refresh(response)

    return response


def complete_assessment(db: Session, session_id: int, student_id: int) -> float:
    session = db.get(AssessmentSession, session_id)

    if session is None or session.student_id != student_id:
        raise ValueError("Assessment not found.")

    questions = db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.session_id == session.id)).all()

    if not questions:
        raise ValueError(("Assessment contains " "no questions."))

    question_ids = [item.id for item in questions]

    responses = db.scalars(
        select(AssessmentResponse).where(
            AssessmentResponse.student_id == student_id,
            AssessmentResponse.question_id.in_(question_ids),
        )
    ).all()

    if len(responses) != len(questions):
        raise ValueError(("Answer every question " "before completing the " "assessment."))

    score = sum(response.score for response in responses) / len(responses)

    session.status = AssessmentStatus.COMPLETED

    session.completed_at = datetime.now(timezone.utc)

    session.score = round(score, 2)

    dimension = ReadinessDimension.CODING if session.kind == AssessmentKind.CODING else ReadinessDimension.APTITUDE

    db.add(
        ReadinessEvidence(
            student_id = student_id,
            dimension = dimension,
            score = session.score,
            source = EvidenceSource.PRACTICE_ASSESSMENT,
            verified = False,
            evidence_text = f"{session.kind.value} " "practice assessment",
            source_entity_type = "assessment_session",
            source_entity_id = session.id,
        )
    )

    db.commit()

    return session.score