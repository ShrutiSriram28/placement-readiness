from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EvidenceSource,
    PlacementOutcome,
    PlacementResult,
    ReadinessDimension,
    ReadinessEvidence,
    RoleProfile,
    StudentProfile
)


def clamp(
    value: float,
    low: float,
    high: float,
) -> float:
    return max(
        low,
        min(
            high,
            value,
        ),
    )


def evidence_quality(
    evidence: ReadinessEvidence,
) -> float:
    source_weights = {
        EvidenceSource.PRACTICE_ASSESSMENT: 0.65,
        EvidenceSource.VERIFIED_ASSESSMENT: 1.0,
        EvidenceSource.LLM: 0.65,
        EvidenceSource.MENTOR: 0.80,
        EvidenceSource.REAL_RECRUITMENT: 1.0,
    }

    base = source_weights[
        evidence.source
    ]

    if evidence.verified:
        base = max(
            base,
            0.95,
        )

    return base


def recency_weight(
    occurred_at: datetime,
) -> float:
    if occurred_at.tzinfo is None:
        occurred_at = (
            occurred_at.replace(
                tzinfo=timezone.utc
            )
        )

    now = datetime.now(
        timezone.utc
    )

    age_days = max(
        0,
        (
            now - occurred_at
        ).total_seconds()
        / 86400,
    )

    return math.exp(
        -age_days / 180
    )


def calculate_dimension_score(
    evidence_items: list[
        ReadinessEvidence
    ],
) -> float | None:
    if not evidence_items:
        return None

    numerator = 0.0
    denominator = 0.0

    for item in evidence_items:
        weight = (
            evidence_quality(
                item
            )
            * recency_weight(
                item.occurred_at
            )
        )

        numerator += (
            item.score
            * weight
        )

        denominator += weight

    if denominator == 0:
        return None

    return round(
        numerator
        / denominator,
        2,
    )


def calculate_confidence(
    evidence_items: list[
        ReadinessEvidence
    ],
) -> float:
    if not evidence_items:
        return 0.0

    count_score = min(
        len(evidence_items)
        / 4,
        1.0,
    )

    quality_score = mean(
        evidence_quality(
            item
        )
        for item
        in evidence_items
    )

    recency_score = mean(
        recency_weight(
            item.occurred_at
        )
        for item
        in evidence_items
    )

    scores = [
        item.score
        for item
        in evidence_items
    ]

    if len(scores) == 1:
        consistency_score = 0.35

    else:
        standard_deviation = (
            pstdev(scores)
        )

        consistency_score = clamp(
            1
            - standard_deviation
            / 30,
            0,
            1,
        )

    return round(
        0.30 * count_score
        + 0.25 * quality_score
        + 0.25 * recency_score
        + 0.20 * consistency_score,
        4,
    )


def calculate_trend(
    evidence_items: list[
        ReadinessEvidence
    ],
) -> str:
    if len(evidence_items) < 2:
        return (
            "insufficient_data"
        )

    ordered = sorted(
        evidence_items,
        key=lambda item:
        item.occurred_at,
    )

    recent = ordered[-3:]

    delta = (
        recent[-1].score
        - recent[0].score
    )

    if delta >= 5:
        return "improving"

    if delta <= -5:
        return "declining"

    return "stable"


def calculate_consistency_dimension(
    evidence_items: list[
        ReadinessEvidence
    ],
) -> float | None:
    meaningful = [
        item
        for item
        in evidence_items
        if item.dimension
        != ReadinessDimension.CONSISTENCY
    ]

    if len(meaningful) < 3:
        return None

    ordered = sorted(
        meaningful,
        key=lambda item:
        item.occurred_at,
    )

    recent = ordered[-8:]

    scores = [
        item.score
        for item
        in recent
    ]

    spread = pstdev(
        scores
    )

    stability = clamp(
        100
        - spread * 2,
        0,
        100,
    )

    return round(
        stability,
        2,
    )


def get_role_profile(
    db: Session,
    company: str,
    role: str,
) -> RoleProfile | None:
    return db.scalar(
        select(
            RoleProfile
        ).where(
            RoleProfile.company_name
            == company,
            RoleProfile.role_name
            == role,
        )
    )


def get_student_readiness(
    db: Session,
    student_id: int,
) -> dict:
    profile = db.scalar(
        select(
            StudentProfile
        ).where(
            StudentProfile.user_id
            == student_id
        )
    )

    evidence = db.scalars(
        select(
            ReadinessEvidence
        )
        .where(
            ReadinessEvidence.student_id
            == student_id
        )
        .order_by(
            ReadinessEvidence.occurred_at
            .asc()
        )
    ).all()

    grouped = defaultdict(
        list
    )

    for item in evidence:
        grouped[
            item.dimension.value
        ].append(
            item
        )

    dimension_scores = {}
    dimension_confidence = {}
    trends = {}

    for dimension in (
        ReadinessDimension
    ):
        items = grouped[
            dimension.value
        ]

        dimension_scores[
            dimension.value
        ] = (
            calculate_dimension_score(
                items
            )
        )

        dimension_confidence[
            dimension.value
        ] = (
            calculate_confidence(
                items
            )
        )

        trends[
            dimension.value
        ] = calculate_trend(
            items
        )

    consistency_score = (
        calculate_consistency_dimension(
            evidence
        )
    )

    if consistency_score is not None:
        dimension_scores[
            ReadinessDimension.CONSISTENCY.value
        ] = consistency_score

        dimension_confidence[
            ReadinessDimension.CONSISTENCY.value
        ] = min(
            len(evidence)
            / 8,
            1,
        )

    if (
        profile is None
        or not profile.target_company
        or not profile.target_role
    ):
        return {
            "overall_score": None,
            "confidence": "low",
            "confidence_score": 0.0,
            "bottleneck": None,
            "dimension_scores": dimension_scores,
            "dimension_confidence": dimension_confidence,
            "trends": trends,
            "missing_dimensions": [],
            "role_profile": None,
        }

    role_profile = (
        get_role_profile(
            db,
            profile.target_company,
            profile.target_role,
        )
    )

    if role_profile is None:
        return {
            "overall_score": None,
            "confidence": "low",
            "confidence_score": 0.0,
            "bottleneck": None,
            "dimension_scores": dimension_scores,
            "dimension_confidence": dimension_confidence,
            "trends": trends,
            "missing_dimensions": [],
            "role_profile": None,
        }

    weights = {
        key: float(value)
        for key, value
        in role_profile.weights.items()
    }

    thresholds = {
        key: float(value)
        for key, value
        in role_profile.thresholds.items()
    }

    relevant = [
        key
        for key, weight
        in weights.items()
        if weight > 0
    ]

    available = []

    for dimension in relevant:
        score = (
            dimension_scores.get(
                dimension
            )
        )

        if score is not None:
            available.append(
                dimension
            )

    missing = [
        dimension
        for dimension
        in relevant
        if dimension
        not in available
    ]

    total_weight = sum(
        weights[dimension]
        for dimension
        in available
    )

    if total_weight:
        overall_score = sum(
            dimension_scores[
                dimension
            ]
            * weights[
                dimension
            ]
            for dimension
            in available
        ) / total_weight

        overall_score = round(
            overall_score,
            2,
        )

    else:
        overall_score = None

    coverage = (
        len(available)
        / len(relevant)
        if relevant
        else 0
    )

    evidence_confidence = (
        mean(
            dimension_confidence[
                dimension
            ]
            for dimension
            in available
        )
        if available
        else 0
    )

    confidence_score = round(
        0.60
        * evidence_confidence
        + 0.40
        * coverage,
        4,
    )

    if confidence_score >= 0.75:
        confidence_label = "high"

    elif confidence_score >= 0.45:
        confidence_label = (
            "medium"
        )

    else:
        confidence_label = "low"

    hard_gate_gaps = []

    for (
        dimension,
        threshold,
    ) in thresholds.items():
        score = (
            dimension_scores.get(
                dimension
            )
        )

        if score is None:
            continue

        if score < threshold:
            hard_gate_gaps.append(
                (
                    dimension,
                    (
                        threshold
                        - score
                    )
                    * max(
                        weights.get(
                            dimension,
                            0,
                        ),
                        0.01,
                    ),
                )
            )

    if hard_gate_gaps:
        bottleneck = max(
            hard_gate_gaps,
            key=lambda item:
            item[1],
        )[0]

    else:
        weighted_gaps = []

        for dimension in available:
            score = (
                dimension_scores[
                    dimension
                ]
            )

            weighted_gaps.append(
                (
                    dimension,
                    (
                        100 - score
                    )
                    * weights[
                        dimension
                    ],
                )
            )

        bottleneck = (
            max(
                weighted_gaps,
                key=lambda item:
                item[1],
            )[0]
            if weighted_gaps
            else None
        )

    return {
        "overall_score": overall_score,
        "confidence": confidence_label,
        "confidence_score": confidence_score,
        "bottleneck": bottleneck,
        "dimension_scores": dimension_scores,
        "dimension_confidence": dimension_confidence,
        "trends": trends,
        "missing_dimensions": missing,
        "role_profile": role_profile,
    }


def calculate_mentor_priority(
    db: Session,
    student_id: int,
) -> dict:
    readiness = (
        get_student_readiness(
            db,
            student_id,
        )
    )

    score = readiness[
        "overall_score"
    ]

    need = (
        0.5
        if score is None
        else clamp(
            (
                100 - score
            )
            / 100,
            0,
            1,
        )
    )

    from app.models import (
        Intervention,
        InterventionStatus,
    )

    interventions = (
        db.scalars(
            select(
                Intervention
            ).where(
                Intervention.student_id
                == student_id
            )
        ).all()
    )

    failed = sum(
        1
        for item in interventions
        if item.status
        == InterventionStatus.FAILED
    )

    intervention_failure = min(
        failed / 2,
        1,
    )

    relevant_trends = [
        trend
        for trend
        in readiness[
            "trends"
        ].values()
        if trend
        != "insufficient_data"
    ]

    declining = (
        sum(
            1
            for trend
            in relevant_trends
            if trend
            == "declining"
        )
        / len(
            relevant_trends
        )
        if relevant_trends
        else 0
    )

    improving = (
        sum(
            1
            for trend
            in relevant_trends
            if trend
            == "improving"
        )
        / len(
            relevant_trends
        )
        if relevant_trends
        else 0
    )

    profile = db.scalar(
        select(
            StudentProfile
        ).where(
            StudentProfile.user_id
            == student_id
        )
    )

    urgency = 0.0

    if (
        profile
        and profile.next_interview_at
    ):
        interview_time = (
            profile.next_interview_at
        )

        if (
            interview_time.tzinfo
            is None
        ):
            interview_time = (
                interview_time.replace(
                    tzinfo=timezone.utc
                )
            )

        days = (
            interview_time
            - datetime.now(
                timezone.utc
            )
        ).total_seconds() / 86400

        if days <= 3:
            urgency = 1.0

        elif days <= 7:
            urgency = 0.7

        elif days <= 14:
            urgency = 0.4

    uncertainty = (
        1
        - readiness[
            "confidence_score"
        ]
    )

    priority = (
        0.35 * need
        + 0.25
        * intervention_failure
        + 0.15 * declining
        + 0.15 * urgency
        + 0.10 * uncertainty
        - 0.10 * improving
    )

    priority = clamp(
        priority,
        0,
        1,
    )

    return {
        "priority_score": round(
            priority * 100,
            2,
        ),
        "need": need,
        "intervention_failure": intervention_failure,
        "declining": declining,
        "improving": improving,
        "urgency": urgency,
        "uncertainty": uncertainty,
    }