from __future__ import annotations
from sqlalchemy.orm import Session
from app.llm_service import llm_service
from app.models import Intervention, InterventionDelivery, ReadinessDimension
from app.readiness_service import get_student_readiness


def delivery_for_dimension(dimension: str) -> InterventionDelivery:
    if dimension in {
        ReadinessDimension.CODING.value,
        ReadinessDimension.APTITUDE.value,
        ReadinessDimension.CONSISTENCY.value,
    }:
        return InterventionDelivery.SELF_PRACTICE

    if dimension == ReadinessDimension.COACHABILITY.value:
        return InterventionDelivery.MENTOR

    return InterventionDelivery.AI


def create_intervention(db: Session, student_id: int, company: str, role: str, created_by_id: int | None) -> Intervention:
    readiness = get_student_readiness(db, student_id)

    bottleneck = readiness["bottleneck"]

    if not bottleneck:
        raise ValueError("The system does not have enough evidence to identify a bottleneck.")

    score = readiness["dimension_scores"].get(bottleneck)

    threshold = None

    role_profile = readiness["role_profile"]

    if role_profile:
        threshold = role_profile.thresholds.get(bottleneck)

    trend = readiness["trends"].get(bottleneck, "unknown")

    ai_plan = (
        llm_service
        .intervention_plan(
            company=company,
            role=role,
            bottleneck=bottleneck,
            current_score=score,
            threshold=threshold,
            trend=trend,
        )
    )

    plan_text = "\n".join(
        [
            f"Objective: {ai_plan.objective}",
            "",
            "Tasks:",
            *[
                f"- {task}"
                for task
                in ai_plan.tasks
            ],
            "",
            "Success criteria:",
            *[
                f"- {item}"
                for item
                in ai_plan.success_criteria
            ],
            "",
            (
                "Reassessment focus: "
                + ai_plan
                .reassessment_focus
            ),
        ]
    )

    intervention = Intervention(
        student_id=student_id,
        dimension=ReadinessDimension(bottleneck),
        delivery=delivery_for_dimension(bottleneck),
        title=ai_plan.title,
        plan=plan_text,
        reason=(
            f"Current system bottleneck: "
            f"{bottleneck}. "
            f"Current score: {score}. "
            f"Target threshold: {threshold}. "
            f"Trend: {trend}."
        ),
        created_by_id=created_by_id,
    )

    db.add(intervention)
    db.commit()
    db.refresh(intervention)

    return intervention