from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, text

from app.database import SessionLocal, engine
from app.models import (
    AssessmentKind,
    AssessmentQuestion,
    AssessmentResponse,
    AssessmentSession,
    AssessmentStatus,
    AuditLog,
    EvidenceSource,
    Intervention,
    InterventionDelivery,
    InterventionStatus,
    InterviewType,
    MentorProfile,
    MentorSession,
    MentorStudentAssignment,
    MockInterview,
    PlacementOutcome,
    PlacementResult,
    PlacementStage,
    QuestionResearch,
    QuestionType,
    ReadinessDimension,
    ReadinessEvidence,
    ResumeAnalysis,
    ResumeDocument,
    RoleProfile,
    StudentProfile,
    User,
    UserRole,
)
from app.security import hash_password


NUM_STUDENTS = 20
NUM_MENTORS = 4
PASSWORD = "abcde1234@#$"

NOW = datetime.now(timezone.utc)

ROLE_CONFIGS = [
    {
        "company": "Amazon",
        "role": "Software Development Engineer",
        "weights": {
            "coding": 0.25,
            "aptitude": 0.10,
            "resume": 0.10,
            "communication": 0.10,
            "project_depth": 0.10,
            "interview": 0.20,
            "consistency": 0.05,
            "coachability": 0.10,
        },
        "thresholds": {
            "coding": 70,
            "aptitude": 60,
            "resume": 65,
            "communication": 65,
            "project_depth": 65,
            "interview": 70,
            "consistency": 60,
            "coachability": 60,
        },
    },
    {
        "company": "Microsoft",
        "role": "Software Engineer",
        "weights": {
            "coding": 0.20,
            "aptitude": 0.10,
            "resume": 0.10,
            "communication": 0.15,
            "project_depth": 0.15,
            "interview": 0.20,
            "consistency": 0.05,
            "coachability": 0.05,
        },
        "thresholds": {
            "coding": 68,
            "aptitude": 60,
            "resume": 65,
            "communication": 70,
            "project_depth": 68,
            "interview": 70,
            "consistency": 60,
            "coachability": 60,
        },
    },
    {
        "company": "Google",
        "role": "Software Engineer",
        "weights": {
            "coding": 0.30,
            "aptitude": 0.10,
            "resume": 0.08,
            "communication": 0.10,
            "project_depth": 0.12,
            "interview": 0.20,
            "consistency": 0.05,
            "coachability": 0.05,
        },
        "thresholds": {
            "coding": 75,
            "aptitude": 65,
            "resume": 65,
            "communication": 65,
            "project_depth": 70,
            "interview": 72,
            "consistency": 60,
            "coachability": 60,
        },
    },
    {
        "company": "Apple",
        "role": "Software Engineer",
        "weights": {
            "coding": 0.20,
            "aptitude": 0.05,
            "resume": 0.10,
            "communication": 0.15,
            "project_depth": 0.20,
            "interview": 0.20,
            "consistency": 0.05,
            "coachability": 0.05,
        },
        "thresholds": {
            "coding": 68,
            "aptitude": 55,
            "resume": 68,
            "communication": 70,
            "project_depth": 72,
            "interview": 70,
            "consistency": 60,
            "coachability": 60,
        },
    },
]


def clear_data():
    """Clear database rows while preserving tables and Tableau views."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names(schema="public")

    if not table_names:
        return

    preparer = engine.dialect.identifier_preparer
    quoted_tables = ", ".join(preparer.quote(name) for name in table_names)

    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                TRUNCATE TABLE {quoted_tables}
                RESTART IDENTITY CASCADE;
                """
            )
        )


def seed_users(db):
    """Create students, mentors, faculty, and their profiles."""
    password_hash = hash_password(PASSWORD)

    faculty = User(
        full_name="faculty1",
        email="faculty1@gmail.com",
        password_hash=password_hash,
        role=UserRole.FACULTY,
        is_active=True,
    )
    db.add(faculty)
    db.flush()

    mentors = []

    expertise_options = [
        ["coding", "technical_interview"],
        ["communication", "behavioral_interview"],
        ["resume", "project_depth"],
        ["aptitude", "interview"],
    ]

    for index in range(1, NUM_MENTORS + 1):
        mentor = User(
            full_name=f"mentor{index}",
            email=f"mentor{index}@gmail.com",
            password_hash=password_hash,
            role=UserRole.MENTOR,
            is_active=True,
        )
        db.add(mentor)
        db.flush()

        db.add(
            MentorProfile(
                user_id=mentor.id,
                weekly_capacity_hours=10,
                expertise=expertise_options[index - 1],
            )
        )

        mentors.append(mentor)

    students = []

    for index in range(1, NUM_STUDENTS + 1):
        role_config = ROLE_CONFIGS[(index - 1) % len(ROLE_CONFIGS)]

        student = User(
            full_name=f"student{index}",
            email=f"student{index}@gmail.com",
            password_hash=password_hash,
            role=UserRole.STUDENT,
            is_active=True,
        )
        db.add(student)
        db.flush()

        db.add(
            StudentProfile(
                user_id=student.id,
                target_company=role_config["company"],
                target_role=role_config["role"],
                target_job_description=(
                    f"Demo job description for {role_config['role']} "
                    f"at {role_config['company']}."
                ),
                next_interview_at=NOW + timedelta(days=7 + index),
            )
        )

        students.append(student)

    return students, mentors, faculty


def seed_role_profiles(db):
    """Create target-role readiness profiles."""
    for config in ROLE_CONFIGS:
        db.add(
            RoleProfile(
                company_name=config["company"],
                role_name=config["role"],
                process_summary=(
                    "Application and resume screening followed by an online "
                    "assessment and technical and behavioral interviews."
                ),
                interview_stages=[
                    {
                        "name": "Resume Screen",
                        "description": "Resume and experience review.",
                        "dimensions": ["resume", "project_depth"],
                    },
                    {
                        "name": "Online Assessment",
                        "description": "Coding and aptitude assessment.",
                        "dimensions": ["coding", "aptitude"],
                    },
                    {
                        "name": "Technical Interview",
                        "description": "Technical problem solving and project discussion.",
                        "dimensions": ["coding", "project_depth", "communication"],
                    },
                    {
                        "name": "Behavioral Interview",
                        "description": "Behavioral and communication evaluation.",
                        "dimensions": ["communication", "interview", "coachability"],
                    },
                ],
                weights=config["weights"],
                thresholds=config["thresholds"],
                research_sources=[],
                research_query=f"{config['company']} {config['role']} interview process",
            )
        )


def seed_question_research(db):
    """Create research records used for generated assessments."""
    for config in ROLE_CONFIGS:
        db.add(
            QuestionResearch(
                company_name=config["company"],
                role_name=config["role"],
                query=f"{config['company']} {config['role']} interview questions",
                sources=[],
                recurring_topics=[
                    "arrays",
                    "hash maps",
                    "graphs",
                    "dynamic programming",
                    "problem solving",
                    "behavioral communication",
                ],
                notable_question_titles=[
                    "Two Sum",
                    "Graph Traversal",
                    "Interval Scheduling",
                ],
            )
        )


def seed_resumes(db, students):
    """Create synthetic resume records and corresponding analyses."""
    resume_analyses = {}

    for index, student in enumerate(students, start=1):
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == student.id).one()

        resume = ResumeDocument(
            student_id=student.id,
            file_name=f"student{index}_resume.pdf",
            extracted_text=(
                f"Student {index}. Computer Science student with experience in "
                "Python, SQL, software engineering, data structures, algorithms, "
                "machine learning, REST APIs, cloud systems, and team projects."
            ),
            uploaded_at=NOW - timedelta(days=80),
        )
        db.add(resume)
        db.flush()

        score = min(92, 55 + index * 1.5)

        analysis = ResumeAnalysis(
            resume_id=resume.id,
            student_id=student.id,
            company_name=profile.target_company,
            role_name=profile.target_role,
            score=score,
            strengths=[
                "Strong technical foundation",
                "Relevant software projects",
            ],
            weaknesses=[
                "Could quantify project impact more clearly",
            ],
            recommendations=[
                "Add measurable project outcomes",
                "Tailor technical keywords to the target role",
            ],
            missing_keywords=["distributed systems"] if index % 2 == 0 else ["cloud"],
            evidence=[
                "Python and SQL experience",
                "Computer science project experience",
            ],
            created_at=NOW - timedelta(days=79),
        )
        db.add(analysis)
        db.flush()

        resume_analyses[student.id] = analysis

    return resume_analyses


def seed_assessments(db, students):
    """Create completed coding and aptitude assessments."""
    sessions_by_student = {}

    for index, student in enumerate(students, start=1):
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == student.id).one()
        student_sessions = []

        for attempt in range(2):
            assessment_date = NOW - timedelta(days=70 - attempt * 30)

            for kind in [AssessmentKind.CODING, AssessmentKind.APTITUDE]:
                base = 48 + index * 1.4 + attempt * 10
                score = min(96, max(35, base + random.randint(-5, 5)))

                session = AssessmentSession(
                    student_id=student.id,
                    kind=kind,
                    company_name=profile.target_company,
                    role_name=profile.target_role,
                    status=AssessmentStatus.COMPLETED,
                    verified=attempt == 1,
                    score=score,
                    started_at=assessment_date,
                    completed_at=assessment_date + timedelta(minutes=45),
                    created_at=assessment_date,
                )
                db.add(session)
                db.flush()

                for position in range(1, 4):
                    if kind == AssessmentKind.CODING:
                        question = AssessmentQuestion(
                            session_id=session.id,
                            position=position,
                            question_type=QuestionType.CODING,
                            title=f"Coding Problem {position}",
                            prompt=f"Solve coding problem {position}.",
                            topic=["arrays", "graphs", "dynamic programming"][position - 1],
                            difficulty=["easy", "medium", "medium"][position - 1],
                            function_name=f"solve_{position}",
                            starter_code=f"def solve_{position}(value):\n    pass",
                            tests=[
                                {"args": [1], "expected": 1},
                                {"args": [2], "expected": 2},
                            ],
                        )
                    else:
                        question = AssessmentQuestion(
                            session_id=session.id,
                            position=position,
                            question_type=QuestionType.MULTIPLE_CHOICE,
                            title=f"Aptitude Question {position}",
                            prompt=f"Demo aptitude problem {position}.",
                            topic=["quantitative", "logical reasoning", "probability"][position - 1],
                            difficulty=["easy", "medium", "medium"][position - 1],
                            choices=["A", "B", "C", "D"],
                            correct_choice_index=1,
                            explanation="B is the correct answer.",
                        )

                    db.add(question)
                    db.flush()

                    response_score = max(0, min(100, score + random.randint(-8, 8)))

                    db.add(
                        AssessmentResponse(
                            question_id=question.id,
                            student_id=student.id,
                            response_text=(
                                "def solution(): return True"
                                if kind == AssessmentKind.CODING
                                else "B"
                            ),
                            score=response_score,
                            feedback="Demo assessment response.",
                            created_at=assessment_date + timedelta(minutes=30),
                        )
                    )

                student_sessions.append(session)

        sessions_by_student[student.id] = student_sessions

    return sessions_by_student


def seed_mock_interviews(db, students):
    """Create completed mock interview records."""
    mocks = {}

    interview_types = [
        InterviewType.GENERAL,
        InterviewType.PROJECT,
        InterviewType.BEHAVIORAL,
    ]

    for index, student in enumerate(students, start=1):
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == student.id).one()
        interview_date = NOW - timedelta(days=35 - index % 8)

        communication = min(95, 50 + index * 1.5 + random.randint(-4, 5))
        project_depth = min(95, 48 + index * 1.7 + random.randint(-4, 5))
        interview_score = min(95, 47 + index * 1.8 + random.randint(-4, 5))

        mock = MockInterview(
            student_id=student.id,
            interview_type=interview_types[(index - 1) % len(interview_types)],
            company_name=profile.target_company,
            role_name=profile.target_role,
            questions=[
                "Tell me about yourself.",
                "Explain one of your projects.",
                "Describe a difficult technical problem you solved.",
            ],
            answers=[
                "Demo answer about background.",
                "Demo project explanation.",
                "Demo technical problem explanation.",
            ],
            evaluation={
                "communication_score": communication,
                "project_depth_score": project_depth,
                "interview_score": interview_score,
                "strengths": ["Clear technical explanation"],
                "weaknesses": ["Could structure examples more concisely"],
                "overall_feedback": "Solid interview with room for improvement.",
            },
            completed=True,
            created_at=interview_date,
        )
        db.add(mock)
        db.flush()

        mocks[student.id] = mock

    return mocks


def seed_mentor_assignments(db, students, mentors, faculty):
    """Assign five students to each mentor."""
    assignments = {}

    for index, student in enumerate(students):
        mentor = mentors[index % len(mentors)]

        assignment = MentorStudentAssignment(
            student_id=student.id,
            mentor_id=mentor.id,
            assigned_by_id=faculty.id,
            active=True,
            created_at=NOW - timedelta(days=75),
        )
        db.add(assignment)
        db.flush()

        assignments[student.id] = assignment

    return assignments


def seed_mentor_capacity(db, mentors):
    """Populate the application's weekly mentor capacity table."""
    week_start = (NOW - timedelta(days=NOW.weekday())).date()

    for mentor in mentors:
        db.execute(
            text(
                """
                INSERT INTO mentor_weekly_capacity
                    (mentor_id, week_start, hours_available)
                VALUES
                    (:mentor_id, :week_start, :hours_available)
                """
            ),
            {
                "mentor_id": mentor.id,
                "week_start": week_start,
                "hours_available": 10,
            },
        )


def seed_mentor_sessions(db, students, assignments):
    """Create historical and upcoming mentor sessions."""
    for index, student in enumerate(students, start=1):
        mentor_id = assignments[student.id].mentor_id

        for offset in [55, 25]:
            db.add(
                MentorSession(
                    student_id=student.id,
                    mentor_id=mentor_id,
                    scheduled_for=NOW - timedelta(days=offset),
                    completed=True,
                    notes="Demo completed mentoring session.",
                )
            )

        db.add(
            MentorSession(
                student_id=student.id,
                mentor_id=mentor_id,
                scheduled_for=NOW + timedelta(days=(index % 6) + 1),
                completed=False,
                notes="Upcoming mentoring session.",
            )
        )


def seed_readiness(
    db,
    students,
    assignments,
    resume_analyses,
    sessions_by_student,
    mocks,
):
    """Create coherent multi-source readiness evidence over time."""
    dimensions = list(ReadinessDimension)

    source_map = {
        ReadinessDimension.CODING: EvidenceSource.VERIFIED_ASSESSMENT,
        ReadinessDimension.APTITUDE: EvidenceSource.VERIFIED_ASSESSMENT,
        ReadinessDimension.RESUME: EvidenceSource.LLM,
        ReadinessDimension.COMMUNICATION: EvidenceSource.LLM,
        ReadinessDimension.PROJECT_DEPTH: EvidenceSource.LLM,
        ReadinessDimension.INTERVIEW: EvidenceSource.LLM,
        ReadinessDimension.CONSISTENCY: EvidenceSource.MENTOR,
        ReadinessDimension.COACHABILITY: EvidenceSource.MENTOR,
    }

    base_offsets = {
        ReadinessDimension.CODING: 1,
        ReadinessDimension.APTITUDE: -3,
        ReadinessDimension.RESUME: 3,
        ReadinessDimension.COMMUNICATION: -1,
        ReadinessDimension.PROJECT_DEPTH: 0,
        ReadinessDimension.INTERVIEW: -4,
        ReadinessDimension.CONSISTENCY: 2,
        ReadinessDimension.COACHABILITY: 4,
    }

    for index, student in enumerate(students, start=1):
        starting_score = 42 + (index % 10) * 3
        mentor_id = assignments[student.id].mentor_id

        for checkpoint in range(4):
            occurred_at = NOW - timedelta(days=75 - checkpoint * 22)

            for dimension in dimensions:
                growth = checkpoint * random.randint(4, 7)
                variation = random.randint(-4, 4)

                if index % 7 == 0:
                    growth = checkpoint * random.randint(1, 3)

                if index % 9 == 0 and checkpoint >= 2:
                    growth -= 5

                score = starting_score + base_offsets[dimension] + growth + variation
                score = float(max(25, min(96, score)))

                source_entity_type = None
                source_entity_id = None
                evaluator_id = None

                if dimension == ReadinessDimension.RESUME:
                    source_entity_type = "resume_analysis"
                    source_entity_id = resume_analyses[student.id].id

                elif dimension in {
                    ReadinessDimension.COMMUNICATION,
                    ReadinessDimension.PROJECT_DEPTH,
                    ReadinessDimension.INTERVIEW,
                }:
                    source_entity_type = "mock_interview"
                    source_entity_id = mocks[student.id].id

                elif dimension in {
                    ReadinessDimension.CODING,
                    ReadinessDimension.APTITUDE,
                }:
                    matching_sessions = [
                        session
                        for session in sessions_by_student[student.id]
                        if (
                            dimension == ReadinessDimension.CODING
                            and session.kind == AssessmentKind.CODING
                        )
                        or (
                            dimension == ReadinessDimension.APTITUDE
                            and session.kind == AssessmentKind.APTITUDE
                        )
                    ]

                    if matching_sessions:
                        source_entity_type = "assessment_session"
                        source_entity_id = matching_sessions[-1].id

                else:
                    evaluator_id = mentor_id

                db.add(
                    ReadinessEvidence(
                        student_id=student.id,
                        dimension=dimension,
                        score=score,
                        source=source_map[dimension],
                        verified=source_map[dimension] == EvidenceSource.VERIFIED_ASSESSMENT,
                        evidence_text=f"Demo {dimension.value} readiness evidence.",
                        source_entity_type=source_entity_type,
                        source_entity_id=source_entity_id,
                        evaluator_id=evaluator_id,
                        occurred_at=occurred_at,
                    )
                )


def seed_interventions(db, students, faculty):
    """Create interventions across all delivery methods."""
    bottlenecks = [
        ReadinessDimension.CODING,
        ReadinessDimension.APTITUDE,
        ReadinessDimension.COMMUNICATION,
        ReadinessDimension.PROJECT_DEPTH,
        ReadinessDimension.INTERVIEW,
    ]

    for index, student in enumerate(students, start=1):
        dimension = bottlenecks[(index - 1) % len(bottlenecks)]

        if dimension in {ReadinessDimension.CODING, ReadinessDimension.APTITUDE}:
            delivery = InterventionDelivery.SELF_PRACTICE
        elif dimension == ReadinessDimension.INTERVIEW:
            delivery = InterventionDelivery.MENTOR
        else:
            delivery = InterventionDelivery.AI

        status = (
            InterventionStatus.COMPLETED
            if index % 5 != 0
            else InterventionStatus.IN_PROGRESS
        )

        db.add(
            Intervention(
                student_id=student.id,
                dimension=dimension,
                delivery=delivery,
                title=f"{dimension.value.replace('_', ' ').title()} Improvement Plan",
                plan=(
                    "Complete targeted practice, review feedback, and reassess "
                    "the identified readiness dimension."
                ),
                reason=f"Identified readiness gap in {dimension.value}.",
                status=status,
                created_by_id=faculty.id,
                created_at=NOW - timedelta(days=42 - index % 10),
            )
        )


def seed_placement_outcomes(db, students):
    """Create varied recruitment funnels and outcomes."""
    stages = [
        PlacementStage.APPLICATION,
        PlacementStage.RESUME_SCREEN,
        PlacementStage.ONLINE_ASSESSMENT,
        PlacementStage.TECHNICAL_INTERVIEW,
        PlacementStage.BEHAVIORAL_INTERVIEW,
        PlacementStage.FINAL_ROUND,
        PlacementStage.OFFER,
    ]

    for index, student in enumerate(students, start=1):
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == student.id).one()

        if index <= 4:
            max_stage = 6
        elif index <= 8:
            max_stage = 5
        elif index <= 13:
            max_stage = 3
        elif index <= 17:
            max_stage = 2
        else:
            max_stage = 1

        for stage_index, stage in enumerate(stages[: max_stage + 1]):
            is_last_stage = stage_index == max_stage

            if stage == PlacementStage.OFFER:
                result = PlacementResult.PASSED
            elif is_last_stage and max_stage < 6:
                result = PlacementResult.FAILED
            else:
                result = PlacementResult.PASSED

            db.add(
                PlacementOutcome(
                    student_id=student.id,
                    company_name=profile.target_company,
                    role_name=profile.target_role,
                    stage=stage,
                    result=result,
                    notes="Synthetic placement outcome for dashboard testing.",
                    occurred_at=NOW - timedelta(days=65 - stage_index * 8 + index % 4),
                )
            )


def seed_audit_logs(db, students, mentors, faculty):
    """Create representative application audit events."""
    db.add(
        AuditLog(
            actor_id=faculty.id,
            action="demo_data_seeded",
            entity_type="database",
            details={"students": len(students), "mentors": len(mentors)},
        )
    )

    for student in students:
        db.add(
            AuditLog(
                actor_id=student.id,
                action="assessment_completed",
                entity_type="student",
                entity_id=student.id,
                details={"source": "demo_seed"},
                created_at=NOW - timedelta(days=random.randint(1, 60)),
            )
        )


def seed_all():
    """Reset and populate the complete demo database."""
    random.seed(42)

    clear_data()

    db = SessionLocal()

    try:
        students, mentors, faculty = seed_users(db)

        seed_role_profiles(db)
        seed_question_research(db)

        resume_analyses = seed_resumes(db, students)
        sessions_by_student = seed_assessments(db, students)
        mocks = seed_mock_interviews(db, students)

        assignments = seed_mentor_assignments(db, students, mentors, faculty)

        seed_mentor_capacity(db, mentors)
        seed_mentor_sessions(db, students, assignments)

        seed_readiness(
            db,
            students,
            assignments,
            resume_analyses,
            sessions_by_student,
            mocks,
        )

        seed_interventions(db, students, faculty)
        seed_placement_outcomes(db, students)
        seed_audit_logs(db, students, mentors, faculty)

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    print("Demo database populated successfully.")
    print(f"Students: {NUM_STUDENTS}")
    print(f"Mentors: {NUM_MENTORS}")
    print("Faculty: 1")
    print("All application tables populated.")


if __name__ == "__main__":
    seed_all()