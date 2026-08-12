from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    STUDENT = "student"
    MENTOR = "mentor"
    FACULTY = "faculty"


class ReadinessDimension(str, Enum):
    CODING = "coding"
    APTITUDE = "aptitude"
    RESUME = "resume"
    COMMUNICATION = "communication"
    PROJECT_DEPTH = "project_depth"
    INTERVIEW = "interview"
    CONSISTENCY = "consistency"
    COACHABILITY = "coachability"


class EvidenceSource(str, Enum):
    PRACTICE_ASSESSMENT = "practice_assessment"
    VERIFIED_ASSESSMENT = "verified_assessment"
    LLM = "llm"
    MENTOR = "mentor"
    REAL_RECRUITMENT = "real_recruitment"


class AssessmentKind(str, Enum):
    CODING = "coding"
    APTITUDE = "aptitude"


class AssessmentStatus(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class QuestionType(str, Enum):
    CODING = "coding"
    MULTIPLE_CHOICE = "multiple_choice"


class InterviewType(str, Enum):
    GENERAL = "general"
    PROJECT = "project"
    BEHAVIORAL = "behavioral"


class InterventionDelivery(str, Enum):
    SELF_PRACTICE = "self_practice"
    AI = "ai"
    MENTOR = "mentor"


class InterventionStatus(str, Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlacementStage(str, Enum):
    APPLICATION = "application"
    RESUME_SCREEN = "resume_screen"
    ONLINE_ASSESSMENT = "online_assessment"
    TECHNICAL_INTERVIEW = "technical_interview"
    BEHAVIORAL_INTERVIEW = "behavioral_interview"
    FINAL_ROUND = "final_round"
    OFFER = "offer"


class PlacementResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"
    WITHDRAWN = "withdrawn"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key = True)

    email: Mapped[str] = mapped_column(String(320), unique = True, index = True)

    full_name: Mapped[str] = mapped_column(String(200))

    password_hash: Mapped[str] = mapped_column(String(512))

    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), index = True)

    is_active: Mapped[bool] = mapped_column(Boolean, default = True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key = True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        unique = True,
        index = True,
    )

    target_company: Mapped[str | None] = mapped_column(String(200), nullable = True)

    target_role: Mapped[str | None] = mapped_column(String(200), nullable = True)

    target_job_description: Mapped[str | None] = mapped_column(Text, nullable = True)

    next_interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone = True), nullable = True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class MentorProfile(Base):
    __tablename__ = "mentor_profiles"

    id: Mapped[int] = mapped_column(primary_key = True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        unique = True,
        index = True,
    )

    weekly_capacity_hours: Mapped[float] = mapped_column(Float, default = 0)

    expertise: Mapped[list] = mapped_column(JSON, default = list)


class RoleProfile(Base):
    __tablename__ = "role_profiles"

    __table_args__ = (
        UniqueConstraint(
            "company_name",
            "role_name",
            name = "uq_role_profile_company_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key = True)

    company_name: Mapped[str] = mapped_column(String(200), index = True)

    role_name: Mapped[str] = mapped_column(String(200), index = True)

    process_summary: Mapped[str] = mapped_column(Text)

    interview_stages: Mapped[list] = mapped_column(JSON)

    weights: Mapped[dict] = mapped_column(JSON)

    thresholds: Mapped[dict] = mapped_column(JSON)

    research_sources: Mapped[list] = mapped_column(JSON)

    research_query: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now, onupdate = utc_now)


class ResumeDocument(Base):
    __tablename__ = "resume_documents"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    file_name: Mapped[str] = mapped_column(String(300))

    extracted_text: Mapped[str] = mapped_column(Text)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id: Mapped[int] = mapped_column(primary_key = True)

    resume_id: Mapped[int] = mapped_column(
        ForeignKey(
            "resume_documents.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    company_name: Mapped[str] = mapped_column(String(200))

    role_name: Mapped[str] = mapped_column(String(200))

    score: Mapped[float] = mapped_column(Float)

    strengths: Mapped[list] = mapped_column(JSON)

    weaknesses: Mapped[list] = mapped_column(JSON)

    recommendations: Mapped[list] = mapped_column(JSON)

    missing_keywords: Mapped[list] = mapped_column(JSON)

    evidence: Mapped[list] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class QuestionResearch(Base):
    __tablename__ = "question_research"

    id: Mapped[int] = mapped_column(primary_key = True)

    company_name: Mapped[str] = mapped_column(String(200), index = True)

    role_name: Mapped[str] = mapped_column(String(200), index = True)

    query: Mapped[str] = mapped_column(Text)

    sources: Mapped[list] = mapped_column(JSON)

    recurring_topics: Mapped[list] = mapped_column(JSON)

    notable_question_titles: Mapped[list] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    kind: Mapped[AssessmentKind] = mapped_column(SAEnum(AssessmentKind), index = True)

    company_name: Mapped[str] = mapped_column(String(200))

    role_name: Mapped[str] = mapped_column(String(200))

    status: Mapped[AssessmentStatus] = mapped_column(SAEnum(AssessmentStatus), default = AssessmentStatus.CREATED)

    verified: Mapped[bool] = mapped_column(Boolean, default = False)

    score: Mapped[float | None] = mapped_column(Float, nullable = True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone = True), nullable = True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone = True), nullable = True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id: Mapped[int] = mapped_column(primary_key = True)

    session_id: Mapped[int] = mapped_column(
        ForeignKey(
            "assessment_sessions.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    position: Mapped[int] = mapped_column(Integer)

    question_type: Mapped[QuestionType] = mapped_column(SAEnum(QuestionType))

    title: Mapped[str] = mapped_column(String(300))

    prompt: Mapped[str] = mapped_column(Text)

    topic: Mapped[str] = mapped_column(String(200))

    difficulty: Mapped[str] = mapped_column(String(100))

    choices: Mapped[list | None] = mapped_column(JSON, nullable = True)

    correct_choice_index: Mapped[int | None] = mapped_column(Integer, nullable = True)

    explanation: Mapped[str | None] = mapped_column(Text, nullable = True)

    function_name: Mapped[str | None] = mapped_column(String(200), nullable = True)

    starter_code: Mapped[str | None] = mapped_column(Text, nullable = True)

    tests: Mapped[list | None] = mapped_column(JSON, nullable = True)


class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "student_id",
            name = "uq_question_student_response",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key = True)

    question_id: Mapped[int] = mapped_column(
        ForeignKey(
            "assessment_questions.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    response_text: Mapped[str] = mapped_column(Text)

    score: Mapped[float] = mapped_column(Float)

    feedback: Mapped[str | None] = mapped_column(Text, nullable = True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class MockInterview(Base):
    __tablename__ = "mock_interviews"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    interview_type: Mapped[InterviewType] = mapped_column(SAEnum(InterviewType))

    company_name: Mapped[str] = mapped_column(String(200))

    role_name: Mapped[str] = mapped_column(String(200))

    questions: Mapped[list] = mapped_column(JSON)

    answers: Mapped[list | None] = mapped_column(JSON, nullable = True)

    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable = True)

    completed: Mapped[bool] = mapped_column(Boolean, default = False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class ReadinessEvidence(Base):
    __tablename__ = "readiness_evidence"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    dimension: Mapped[ReadinessDimension] = mapped_column(SAEnum(ReadinessDimension), index = True)

    score: Mapped[float] = mapped_column(Float)

    source: Mapped[EvidenceSource] = mapped_column(SAEnum(EvidenceSource))

    verified: Mapped[bool] = mapped_column(Boolean, default = False)

    evidence_text: Mapped[str | None] = mapped_column(Text, nullable = True)

    source_entity_type: Mapped[str | None] = mapped_column(String(100), nullable = True)

    source_entity_id: Mapped[int | None] = mapped_column(Integer, nullable = True)

    evaluator_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "SET NULL",
        ),
        nullable = True,
    )

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now, index = True)


class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    dimension: Mapped[ReadinessDimension] = mapped_column(SAEnum(ReadinessDimension), index = True)

    delivery: Mapped[InterventionDelivery] = mapped_column(SAEnum(InterventionDelivery))

    title: Mapped[str] = mapped_column(String(300))

    plan: Mapped[str] = mapped_column(Text)

    reason: Mapped[str] = mapped_column(Text)

    status: Mapped[InterventionStatus] = mapped_column(SAEnum(InterventionStatus), default = InterventionStatus.ASSIGNED)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "SET NULL",
        ),
        nullable = True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class MentorStudentAssignment(Base):
    __tablename__ = "mentor_student_assignments"

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "mentor_id",
            name = "uq_student_mentor_assignment",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    mentor_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    active: Mapped[bool] = mapped_column(Boolean, default = True)

    assigned_by_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "RESTRICT",
        )
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class MentorSession(Base):
    __tablename__ = "mentor_sessions"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    mentor_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone = True), index = True)

    completed: Mapped[bool] = mapped_column(Boolean, default = False)

    notes: Mapped[str | None] = mapped_column(Text, nullable = True)


class PlacementOutcome(Base):
    __tablename__ = "placement_outcomes"

    id: Mapped[int] = mapped_column(primary_key = True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "CASCADE",
        ),
        index = True,
    )

    company_name: Mapped[str] = mapped_column(String(200))

    role_name: Mapped[str] = mapped_column(String(200))

    stage: Mapped[PlacementStage] = mapped_column(SAEnum(PlacementStage))

    result: Mapped[PlacementResult] = mapped_column(SAEnum(PlacementResult))

    notes: Mapped[str | None] = mapped_column(Text, nullable = True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key = True)

    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete = "SET NULL",
        ),
        nullable = True,
        index = True,
    )

    action: Mapped[str] = mapped_column(String(200), index = True)

    entity_type: Mapped[str | None] = mapped_column(String(100), nullable = True)

    entity_id: Mapped[int | None] = mapped_column(Integer, nullable = True)

    details: Mapped[dict | None] = mapped_column(JSON, nullable = True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), default = utc_now)