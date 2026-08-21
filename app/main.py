from __future__ import annotations

import json

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from nicegui import app, events, run, ui
from sqlalchemy import Column, Date, Float, ForeignKey, Integer, Table, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError

from app.assessment_service import (
    complete_assessment,
    create_aptitude_assessment,
    create_coding_assessment,
    research_questions,
    save_aptitude_response,
    save_coding_response,
)
from app.config import settings
from app.database import Base, SessionLocal, engine, create_tableau_views
from app.internet_tool import internet_tool
from app.intervention_service import create_intervention
from app.llm_service import llm_service
from app.models import (
    AssessmentKind,
    AssessmentQuestion,
    AssessmentResponse,
    AssessmentSession,
    AssessmentStatus,
    AuditLog,
    EvidenceSource,
    Intervention,
    InterviewType,
    MentorProfile,
    MentorSession,
    MentorStudentAssignment,
    MockInterview,
    PlacementOutcome,
    PlacementResult,
    PlacementStage,
    QuestionResearch,
    ReadinessDimension,
    ReadinessEvidence,
    ResumeAnalysis,
    ResumeDocument,
    RoleProfile,
    StudentProfile,
    User,
    UserRole,
)
from app.readiness_service import (
    calculate_mentor_priority,
    get_role_profile,
    get_student_readiness,
)
from app.resume_service import ResumeParseError, extract_resume_text
from app.security import hash_password, verify_password


mentor_weekly_capacity = Table(
    "mentor_weekly_capacity",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mentor_id", ForeignKey("users.id"), nullable=False),
    Column("week_start", Date, nullable=False),
    Column("hours_available", Float, nullable=False),
    UniqueConstraint(
        "mentor_id",
        "week_start",
        name="uq_mentor_weekly_capacity",
    ),
)


Base.metadata.create_all(bind=engine)
create_tableau_views()


def db_session():
    return SessionLocal()


def audit(
    db,
    actor_id,
    action,
    entity_type=None,
    entity_id=None,
    details=None,
):
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )


def current_user():
    user_id = app.storage.user.get("user_id")

    if not user_id:
        return None

    db = db_session()

    try:
        user = db.get(User, int(user_id))

        if user:
            db.expunge(user)

        return user

    finally:
        db.close()


def require_user():
    user = current_user()

    if not user:
        ui.navigate.to("/login")
        return None

    return user


def require_role(*roles):
    user = require_user()

    if not user:
        return None

    if user.role not in roles:
        ui.notify(
            "You do not have permission to access this page.",
            type="negative",
        )
        ui.navigate.to("/")
        return None

    return user


def navigation(user):
    with ui.header().classes(
        "items-center justify-between px-6"
    ):
        ui.label(
            settings.app_name
        ).classes(
            "text-lg font-semibold"
        )

        with ui.row().classes(
            "items-center gap-3"
        ):
            ui.label(
                user.full_name
            ).classes(
                "text-white"
            )

            ui.button(
                "Dashboard",
                icon="dashboard",
                on_click=lambda: ui.navigate.to(
                    "/"
                ),
            ).props(
                "flat color=white"
            )

            def logout():
                app.storage.user.clear()

                ui.navigate.to(
                    "/login"
                )

            ui.button(
                "Logout",
                icon="logout",
                on_click=logout,
            ).props(
                "flat color=white"
            )


def heading(
    title,
    subtitle=None,
):
    ui.label(
        title
    ).classes(
        "text-3xl font-bold"
    )

    if subtitle:
        ui.label(
            subtitle
        ).classes(
            "text-gray-600"
        )


def section_heading(title, description):
    ui.label(title).classes("text-2xl font-semibold")
    ui.label(description).classes("text-gray-600 mb-4")


TABLEAU_ALL = "__all__"

TABLEAU_READINESS_AREAS = {
    TABLEAU_ALL: "All readiness areas",
    "Aptitude": "Aptitude",
    "Coachability": "Coachability",
    "Coding": "Coding",
    "Communication": "Communication",
    "Consistency": "Consistency",
    "Interview Skills": "Interview Skills",
    "Project Depth": "Project Depth",
    "Resume Quality": "Resume Quality",
}

TABLEAU_ASSESSMENTS_BY_READINESS_AREA = {
    "Aptitude": ["Aptitude Assessment"],
    "Coding": ["Coding Assessment"],
    "Communication": ["AI Mock Interview"],
    "Interview Skills": ["AI Mock Interview"],
    "Project Depth": ["AI Mock Interview"],
    "Resume Quality": ["AI Mock Interview"],
    "Coachability": [
        "AI Mock Interview",
        "Aptitude Assessment",
        "Coding Assessment",
    ],
    "Consistency": [
        "AI Mock Interview",
        "Aptitude Assessment",
        "Coding Assessment",
    ],
}

TABLEAU_STUDENT_URL = (
    "https://public.tableau.com/views/"
    "student_dashboard_placement_readiness_analytics/"
    "StudentDashboard"
)

TABLEAU_MENTOR_URL = (
    "https://public.tableau.com/views/"
    "mentor_dashboard_placement_readiness_analytics/"
    "MentorDashboard"
)

TABLEAU_FACULTY_URL = (
    "https://public.tableau.com/views/"
    "faculty_dashboard_placement_readiness_analytics/"
    "FacultyDashboard"
)


def tableau_view_url(base_url, filters=None):
    url = (
        f"{base_url}"
        "?:showVizHome=no"
        "&:embed=yes"
        "&:device=desktop"
        "&:toolbar=no"
    )

    for field, value in (filters or {}).items():
        if value in (None, "", TABLEAU_ALL):
            continue

        url += (
            f"&{quote(str(field), safe='')}="
            f"{quote(str(value), safe='')}"
        )

    return url


def tableau_iframe(url, height=1200):
    return f"""
    <div style="
        width: 1200px;
        max-width: 100%;
        height: {height}px;
        margin: 0 auto;
        overflow: hidden;
    ">
        <iframe
            src="{url}"
            style="
                width: 1200px;
                height: {height}px;
                max-width: none;
                border: 0;
                display: block;
            "
            frameborder="0"
            allowfullscreen>
        </iframe>
    </div>
    """


def tableau_viz_element(base_url, viz_id, height=1200):
    return f"""
    <div style="
        width: 1200px;
        max-width: 100%;
        height: {height}px;
        margin: 0 auto;
        overflow: hidden;
    ">
        <tableau-viz
            id="{viz_id}"
            src="{base_url}"
            width="1200"
            height="{height}"
            toolbar="hidden"
            hide-tabs>
        </tableau-viz>
    </div>
    """


def clean_target(value):
    return (
        value or ""
    ).strip()


def student_profile_for(
    db,
    user_id,
):
    return db.scalar(
        select(
            StudentProfile
        ).where(
            StudentProfile.user_id
            == user_id
        )
    )


def latest_resume_for(
    db,
    user_id,
):
    return db.scalar(
        select(
            ResumeDocument
        )
        .where(
            ResumeDocument.student_id
            == user_id
        )
        .order_by(
            ResumeDocument.uploaded_at.desc()
        )
    )


def research_role_profile(
    db,
    company,
    role,
):
    query = (
        f"{company} {role} "
        "interview process hiring stages "
        "coding technical behavioral "
        "assessment interview experience"
    )

    raw = internet_tool.search(
        query
    )

    sources = (
        internet_tool
        .compact_results(
            raw
        )
    )

    output = (
        llm_service
        .role_profile(
            company,
            role,
            sources,
        )
    )

    weights = (
        output.weights
        .model_dump()
    )

    total = sum(
        weights.values()
    )

    if total <= 0:
        raise ValueError(
            "Could not determine relevant readiness dimensions."
        )

    normalized_weights = {
        key: value / total
        for key, value
        in weights.items()
    }

    thresholds = (
        output.thresholds
        .model_dump()
    )

    existing = get_role_profile(
        db,
        company,
        role,
    )

    stages = [
        stage.model_dump()
        for stage
        in output.stages
    ]

    if existing:
        existing.process_summary = (
            output.process_summary
        )

        existing.interview_stages = (
            stages
        )

        existing.weights = (
            normalized_weights
        )

        existing.thresholds = (
            thresholds
        )

        existing.research_sources = (
            sources
        )

        existing.research_query = (
            query
        )

        db.commit()
        db.refresh(
            existing
        )

        return existing

    record = RoleProfile(
        company_name=company,
        role_name=role,
        process_summary=(
            output.process_summary
        ),
        interview_stages=stages,
        weights=normalized_weights,
        thresholds=thresholds,
        research_sources=sources,
        research_query=query,
    )

    db.add(
        record
    )

    db.commit()
    db.refresh(
        record
    )

    return record


@ui.page("/login")
def login_page():
    if app.storage.user.get(
        "user_id"
    ):
        ui.navigate.to("/")
        return

    with ui.column().classes(
        "w-full max-w-md mx-auto mt-20 gap-4"
    ):
        heading(
            "Sign in"
        )

        email = ui.input(
            "Email"
        ).props(
            "type=email"
        ).classes(
            "w-full"
        )

        password = ui.input(
            "Password",
            password=True,
            password_toggle_button=True,
        ).classes(
            "w-full"
        )

        def login():
            db = db_session()

            try:
                normalized = (
                    clean_target(
                        email.value
                    ).lower()
                )

                user = db.scalar(
                    select(
                        User
                    ).where(
                        User.email
                        == normalized
                    )
                )

                if (
                    not user
                    or not user.is_active
                    or not verify_password(
                        password.value
                        or "",
                        user.password_hash,
                    )
                ):
                    ui.notify(
                        "Invalid email or password.",
                        type="negative",
                    )
                    return

                app.storage.user[
                    "user_id"
                ] = user.id

                audit(
                    db,
                    user.id,
                    "login",
                    "user",
                    user.id,
                )

                db.commit()

                ui.navigate.to("/")

            finally:
                db.close()

        ui.button(
            "Sign in",
            on_click=login,
        ).classes(
            "w-full"
        )

        ui.button(
            "Create account",
            on_click=lambda:
                ui.navigate.to(
                    "/signup"
                ),
        ).props(
            "flat"
        )


@ui.page("/signup")
def signup_page():
    if app.storage.user.get(
        "user_id"
    ):
        ui.navigate.to("/")
        return

    with ui.column().classes(
        "w-full max-w-md mx-auto mt-12 gap-4"
    ):
        heading(
            "Create account"
        )

        name = ui.input(
            "Full name"
        ).classes(
            "w-full"
        )

        email = ui.input(
            "Email"
        ).props(
            "type=email"
        ).classes(
            "w-full"
        )

        password = ui.input(
            "Password",
            password=True,
            password_toggle_button=True,
        ).classes(
            "w-full"
        )

        role = ui.select(
            {
                UserRole.STUDENT.value:
                    "Student",
                UserRole.MENTOR.value:
                    "Mentor",
                UserRole.FACULTY.value:
                    "Faculty",
            },
            value=(
                UserRole.STUDENT.value
            ),
            label="Role",
        ).classes(
            "w-full"
        )

        staff_code = ui.input(
            "Staff signup code",
            password=True,
            password_toggle_button=True,
        ).classes(
            "w-full"
        )

        def signup():
            name_value = clean_target(
                name.value
            )

            email_value = clean_target(
                email.value
            ).lower()

            password_value = (
                password.value
                or ""
            )

            if not name_value:
                ui.notify(
                    "Name is required.",
                    type="warning",
                )
                return

            if (
                not email_value
                or "@"
                not in email_value
            ):
                ui.notify(
                    "Enter a valid email.",
                    type="warning",
                )
                return

            if len(
                password_value
            ) < 12:
                ui.notify(
                    "Password must contain at least 12 characters.",
                    type="warning",
                )
                return

            selected_role = (
                UserRole(
                    role.value
                )
            )

            if (
                selected_role
                != UserRole.STUDENT
                and staff_code.value
                != settings.staff_signup_code
            ):
                ui.notify(
                    "Invalid staff signup code.",
                    type="negative",
                )
                return

            db = db_session()

            try:
                user = User(
                    email=email_value,
                    full_name=name_value,
                    password_hash=(
                        hash_password(
                            password_value
                        )
                    ),
                    role=selected_role,
                )

                db.add(
                    user
                )

                db.flush()

                if (
                    selected_role
                    == UserRole.STUDENT
                ):
                    db.add(
                        StudentProfile(
                            user_id=user.id
                        )
                    )

                elif (
                    selected_role
                    == UserRole.MENTOR
                ):
                    db.add(
                        MentorProfile(
                            user_id=user.id
                        )
                    )

                audit(
                    db,
                    user.id,
                    "signup",
                    "user",
                    user.id,
                )

                db.commit()

                app.storage.user[
                    "user_id"
                ] = user.id

                ui.navigate.to("/")

            except IntegrityError:
                db.rollback()

                ui.notify(
                    "An account with this email already exists.",
                    type="negative",
                )

            finally:
                db.close()

        ui.button(
            "Create account",
            on_click=signup,
        ).classes(
            "w-full"
        )


@ui.page("/")
def home():
    user = require_user()

    if not user:
        return

    if (
        user.role
        == UserRole.STUDENT
    ):
        ui.navigate.to(
            "/student"
        )

    elif (
        user.role
        == UserRole.MENTOR
    ):
        ui.navigate.to(
            "/mentor"
        )

    else:
        ui.navigate.to(
            "/faculty"
        )


@ui.page("/student")
def student_page():
    user = require_role(
        UserRole.STUDENT
    )

    if not user:
        return

    navigation(
        user
    )

    db = db_session()

    try:
        profile = (
            student_profile_for(
                db,
                user.id,
            )
        )

        readiness = (
            get_student_readiness(
                db,
                user.id,
            )
        )

        latest_resume = (
            latest_resume_for(
                db,
                user.id,
            )
        )

        interventions = (
            db.scalars(
                select(
                    Intervention
                )
                .where(
                    Intervention.student_id
                    == user.id
                )
                .order_by(
                    Intervention.created_at
                    .desc()
                )
            ).all()
        )

        sessions = (
            db.scalars(
                select(
                    AssessmentSession
                )
                .where(
                    AssessmentSession.student_id
                    == user.id
                )
                .order_by(
                    AssessmentSession.created_at
                    .desc()
                )
            ).all()
        )

        mocks = (
            db.scalars(
                select(
                    MockInterview
                )
                .where(
                    MockInterview.student_id
                    == user.id
                )
                .order_by(
                    MockInterview.created_at
                    .desc()
                )
            ).all()
        )

        student_mentor_sessions = (
            db.scalars(
                select(
                    MentorSession
                )
                .where(
                    MentorSession.student_id
                    == user.id,
                    MentorSession.scheduled_for
                    >= datetime.now(
                        timezone.utc
                    ),
                )
                .order_by(
                    MentorSession.scheduled_for
                )
            ).all()
        )

        def show_student_section(name):
            sections = {
                "overview": overview_panel,
                "target": target_panel,
                "resume": resume_panel,
                "research": research_panel,
                "assessments": assessments_panel,
                "mock": mock_panel,
                "interventions": interventions_panel,
                "outcomes": outcomes_panel,
                "analytics": analytics_panel,
            }
            for section_name, panel in sections.items():
                panel.set_visibility(section_name == name)

        with ui.left_drawer(value=True).props("bordered width=260 breakpoint=700").classes("bg-white px-2 pt-2 pb-3 shadow-sm") as student_drawer:
            with ui.row().classes("w-full justify-start items-center mb-2"):
                ui.button(icon="menu", on_click=student_drawer.toggle).props("round dense flat color=primary").tooltip("Collapse navigation")
            ui.button("Readiness Overview", icon="dashboard", on_click=lambda: show_student_section("overview")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Target Company & Role", icon="flag", on_click=lambda: show_student_section("target")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Resume Analysis", icon="description", on_click=lambda: show_student_section("resume")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Question Research", icon="search", on_click=lambda: show_student_section("research")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Coding & Aptitude", icon="quiz", on_click=lambda: show_student_section("assessments")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("AI Mock Interview", icon="record_voice_over", on_click=lambda: show_student_section("mock")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Intervention Plan", icon="event_note", on_click=lambda: show_student_section("interventions")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Placement Outcomes", icon="work", on_click=lambda: show_student_section("outcomes")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Placement Analytics", icon="analytics", on_click=lambda: show_student_section("analytics")).props("flat no-caps align=left").classes("w-full justify-start text-left")

        with ui.page_sticky(position="top-left", x_offset=8, y_offset=8):
            student_open_button = ui.button(icon="menu", on_click=student_drawer.toggle).props("round dense unelevated color=primary").tooltip("Open navigation")
            student_open_button.bind_visibility_from(student_drawer, "value", backward=lambda value: not value)

        with ui.column().classes(
            "w-full max-w-7xl mx-auto p-6 gap-6"
        ):
            heading(
                "Student dashboard",
                (
                    "Readiness is evaluated against "
                    "your target company and role."
                ),
            )

            with ui.column().classes("w-full gap-4") as overview_panel:
                section_heading("Readiness Overview", "Your overall readiness, confidence, bottleneck, upcoming mentor sessions, and dimension-level scores.")
                with ui.row().classes(
                    "w-full gap-4 flex-wrap"
                ):
                    with ui.card().classes(
                        "min-w-64 flex-1"
                    ):
                        ui.label(
                            "Overall readiness"
                        )

                        ui.label(
                            (
                                f"{readiness['overall_score']:.1f}%"
                                if readiness[
                                    "overall_score"
                                ]
                                is not None
                                else "Insufficient data"
                            )
                        ).classes(
                            "text-3xl font-bold"
                        )

                    with ui.card().classes(
                        "min-w-64 flex-1"
                    ):
                        ui.label(
                            "Confidence"
                        )

                        ui.label(
                            readiness[
                                "confidence"
                            ].title()
                        ).classes(
                            "text-3xl font-bold"
                        )

                    with ui.card().classes(
                        "min-w-64 flex-1"
                    ):
                        ui.label(
                            "Current bottleneck"
                        )

                        bottleneck = (
                            readiness[
                                "bottleneck"
                            ]
                        )

                        ui.label(
                            (
                                bottleneck
                                .replace(
                                    "_",
                                    " ",
                                )
                                .title()
                                if bottleneck
                                else "Unknown"
                            )
                        ).classes(
                            "text-2xl font-bold"
                        )

                ui.separator()

                ui.label(
                    "Upcoming mentor sessions"
                ).classes(
                    "text-2xl font-semibold"
                )

                if not student_mentor_sessions:
                    ui.label(
                        "No mentor sessions are currently scheduled."
                    ).classes(
                        "text-gray-600"
                    )

                else:
                    for mentor_session in (
                        student_mentor_sessions
                    ):
                        mentor = db.get(
                            User,
                            mentor_session.mentor_id,
                        )

                        with ui.card().classes(
                            "w-full"
                        ):
                            ui.label(
                                (
                                    mentor.full_name
                                    if mentor
                                    else "Mentor"
                                )
                            ).classes(
                                "text-lg font-semibold"
                            )

                            ui.label(
                                mentor_session
                                .scheduled_for
                                .strftime(
                                    "%B %d, %Y at %I:%M %p UTC"
                                )
                            )

                            if mentor_session.notes:
                                ui.label(
                                    mentor_session.notes
                                ).classes(
                                    "text-gray-600"
                                )

                ui.separator()

                ui.label(
                    "Readiness dimensions"
                ).classes(
                    "text-2xl font-semibold"
                )

                dimension_rows = []

                for dimension in (
                    ReadinessDimension
                ):
                    score = (
                        readiness[
                            "dimension_scores"
                        ].get(
                            dimension.value
                        )
                    )

                    confidence = (
                        readiness[
                            "dimension_confidence"
                        ].get(
                            dimension.value,
                            0,
                        )
                    )

                    dimension_rows.append(
                        {
                            "dimension": (
                                dimension.value
                                .replace(
                                    "_",
                                    " ",
                                )
                                .title()
                            ),
                            "score": (
                                round(
                                    score,
                                    1,
                                )
                                if score
                                is not None
                                else "Unknown"
                            ),
                            "confidence": (
                                f"{confidence * 100:.0f}%"
                            ),
                            "trend": (
                                readiness[
                                    "trends"
                                ]
                                .get(
                                    dimension.value,
                                    "unknown",
                                )
                                .replace(
                                    "_",
                                    " ",
                                )
                                .title()
                            ),
                        }
                    )

                ui.table(
                    columns=[
                        {
                            "name": "dimension",
                            "label": "Dimension",
                            "field": "dimension",
                        },
                        {
                            "name": "score",
                            "label": "Score",
                            "field": "score",
                        },
                        {
                            "name": "confidence",
                            "label": "Confidence",
                            "field": "confidence",
                        },
                        {
                            "name": "trend",
                            "label": "Trend",
                            "field": "trend",
                        },
                    ],
                    rows=dimension_rows,
                    row_key="dimension",
                ).classes(
                    "w-full"
                )

            with ui.column().classes("w-full gap-4") as target_panel:
                section_heading("Target Company & Role", "Set the company, role, and job description used to personalize your preparation.")
                with ui.card().classes(
                    "w-full"
                ):
                    ui.label(
                        "Target"
                    ).classes(
                        "text-xl font-semibold"
                    )

                    company = ui.input(
                        "Target company",
                        value=(
                            profile.target_company
                            or ""
                        ),
                    ).classes(
                        "w-full"
                    )

                    role = ui.input(
                        "Target role",
                        value=(
                            profile.target_role
                            or ""
                        ),
                    ).classes(
                        "w-full"
                    )

                    job_description = (
                        ui.textarea(
                            "Job description",
                            value=(
                                profile
                                .target_job_description
                                or ""
                            ),
                        ).classes(
                            "w-full"
                        )
                    )

                    async def save_target():
                        print(
                            "CLICK: save_target",
                            flush=True,
                        )

                        company_value = (
                            clean_target(
                                company.value
                            )
                        )

                        role_value = (
                            clean_target(
                                role.value
                            )
                        )

                        job_description_value = (
                            clean_target(
                                job_description.value
                            )
                        )

                        if (
                            not company_value
                            or not role_value
                        ):
                            ui.notify(
                                "Company and role are required.",
                                type="warning",
                            )
                            return

                        ui.notify(
                            "Researching current interview information..."
                        )

                        def work():
                            local_db = (
                                db_session()
                            )

                            try:
                                local_profile = (
                                    student_profile_for(
                                        local_db,
                                        user.id,
                                    )
                                )

                                local_profile.target_company = (
                                    company_value
                                )

                                local_profile.target_role = (
                                    role_value
                                )

                                local_profile.target_job_description = (
                                    job_description_value
                                    or None
                                )

                                local_db.commit()

                                research_role_profile(
                                    local_db,
                                    company_value,
                                    role_value,
                                )

                            finally:
                                local_db.close()

                        try:
                            await run.io_bound(
                                work
                            )

                            ui.notify(
                                (
                                    "Target saved and readiness "
                                    "profile researched."
                                ),
                                type="positive",
                            )

                            ui.navigate.to(
                                "/student"
                            )

                        except Exception as exc:
                            ui.notify(
                                (
                                    "Could not research target: "
                                    f"{exc}"
                                ),
                                type="negative",
                            )

                    ui.button(
                        "Save and research target",
                        on_click=save_target,
                    )

            with ui.column().classes("w-full gap-4") as resume_panel:
                section_heading("Resume Analysis", "Upload your resume and receive a role-specific score, strengths, weaknesses, and recommendations.")
                ui.separator()

                ui.label(
                    "Resume"
                ).classes(
                    "text-2xl font-semibold"
                )

                upload_state = {
                    "file_name": None,
                    "content": None,
                }

                async def upload_resume(
                    e: events.UploadEventArguments,
                ):
                    upload_state[
                        "file_name"
                    ] = e.file.name

                    upload_state[
                        "content"
                    ] = await e.file.read()

                    ui.notify(
                        (
                            f"{e.file.name} "
                            "ready for analysis."
                        )
                    )

                ui.upload(
                    label=(
                        "Upload PDF, DOCX, "
                        "or TXT resume"
                    ),
                    on_upload=upload_resume,
                    auto_upload=True,
                    max_files=1,
                    max_file_size=10_000_000,
                ).props(
                    "accept=.pdf,.docx,.txt"
                ).classes(
                    "w-full"
                )

                async def analyze_resume():
                    print(
                        "CLICK: analyze_resume",
                        flush=True,
                    )

                    current_company = (
                        profile.target_company
                    )

                    current_role = (
                        profile.target_role
                    )

                    file_name = (
                        upload_state[
                            "file_name"
                        ]
                    )

                    file_content = (
                        upload_state[
                            "content"
                        ]
                    )

                    if (
                        not current_company
                        or not current_role
                    ):
                        ui.notify(
                            (
                                "Set your target company "
                                "and role first."
                            ),
                            type="warning",
                        )
                        return

                    if not file_content:
                        ui.notify(
                            "Upload a resume first.",
                            type="warning",
                        )
                        return

                    try:
                        text = (
                            extract_resume_text(
                                file_name,
                                file_content,
                            )
                        )

                    except ResumeParseError as exc:
                        ui.notify(
                            str(exc),
                            type="negative",
                        )
                        return

                    ui.notify(
                        "Analyzing resume..."
                    )

                    def work():
                        local_db = (
                            db_session()
                        )

                        try:
                            local_profile = (
                                student_profile_for(
                                    local_db,
                                    user.id,
                                )
                            )

                            role_profile = (
                                get_role_profile(
                                    local_db,
                                    local_profile
                                    .target_company,
                                    local_profile
                                    .target_role,
                                )
                            )

                            resume = (
                                ResumeDocument(
                                    student_id=user.id,
                                    file_name=file_name,
                                    extracted_text=text,
                                )
                            )

                            local_db.add(
                                resume
                            )

                            local_db.flush()

                            role_data = None

                            if role_profile:
                                role_data = {
                                    "process_summary":
                                        role_profile
                                        .process_summary,
                                    "weights":
                                        role_profile
                                        .weights,
                                    "thresholds":
                                        role_profile
                                        .thresholds,
                                }

                            result = (
                                llm_service
                                .resume_analysis(
                                    resume_text=text,
                                    company=(
                                        local_profile
                                        .target_company
                                    ),
                                    role=(
                                        local_profile
                                        .target_role
                                    ),
                                    job_description=(
                                        local_profile
                                        .target_job_description
                                        or ""
                                    ),
                                    role_profile=(
                                        role_data
                                    ),
                                )
                            )

                            analysis = (
                                ResumeAnalysis(
                                    resume_id=resume.id,
                                    student_id=user.id,
                                    company_name=(
                                        local_profile
                                        .target_company
                                    ),
                                    role_name=(
                                        local_profile
                                        .target_role
                                    ),
                                    score=(
                                        result.score
                                    ),
                                    strengths=(
                                        result.strengths
                                    ),
                                    weaknesses=(
                                        result.weaknesses
                                    ),
                                    recommendations=(
                                        result
                                        .recommendations
                                    ),
                                    missing_keywords=(
                                        result
                                        .missing_keywords
                                    ),
                                    evidence=(
                                        result.evidence
                                    ),
                                )
                            )

                            local_db.add(
                                analysis
                            )

                            local_db.flush()

                            local_db.add(
                                ReadinessEvidence(
                                    student_id=user.id,
                                    dimension=(
                                        ReadinessDimension
                                        .RESUME
                                    ),
                                    score=(
                                        result.score
                                    ),
                                    source=(
                                        EvidenceSource
                                        .LLM
                                    ),
                                    verified=False,
                                    evidence_text=(
                                        "\n".join(
                                            result.evidence
                                        )
                                    ),
                                    source_entity_type=(
                                        "resume_analysis"
                                    ),
                                    source_entity_id=(
                                        analysis.id
                                    ),
                                )
                            )

                            local_db.commit()

                        finally:
                            local_db.close()

                    try:
                        await run.io_bound(
                            work
                        )

                        ui.notify(
                            "Resume analyzed.",
                            type="positive",
                        )

                        ui.navigate.to(
                            "/student"
                        )

                    except Exception as exc:
                        ui.notify(
                            (
                                "Resume analysis failed: "
                                f"{exc}"
                            ),
                            type="negative",
                        )

                ui.button(
                    "Analyze resume",
                    on_click=analyze_resume,
                )

                analyses = (
                    db.scalars(
                        select(
                            ResumeAnalysis
                        )
                        .where(
                            ResumeAnalysis.student_id
                            == user.id
                        )
                        .order_by(
                            ResumeAnalysis
                            .created_at
                            .desc()
                        )
                        .limit(
                            1
                        )
                    ).all()
                )

                if analyses:
                    analysis = analyses[0]

                    with ui.card().classes(
                        "w-full"
                    ):
                        ui.label(
                            (
                                "Latest resume score: "
                                f"{analysis.score:.1f}%"
                            )
                        ).classes(
                            "text-xl font-bold"
                        )

                        ui.label(
                            "Strengths"
                        ).classes(
                            "font-semibold"
                        )

                        for item in (
                            analysis.strengths
                        ):
                            ui.label(
                                f"• {item}"
                            )

                        ui.label(
                            "Weaknesses"
                        ).classes(
                            "font-semibold mt-3"
                        )

                        for item in (
                            analysis.weaknesses
                        ):
                            ui.label(
                                f"• {item}"
                            )

                        ui.label(
                            "Recommendations"
                        ).classes(
                            "font-semibold mt-3"
                        )

                        for item in (
                            analysis.recommendations
                        ):
                            ui.label(
                                f"• {item}"
                            )

            with ui.column().classes("w-full gap-4") as research_panel:
                section_heading("Question Research", "Search current interview information, recurring topics, reported questions, and sources.")
                ui.separator()

                ui.label(
                    (
                        "Company / role "
                        "question research"
                    )
                ).classes(
                    "text-2xl font-semibold"
                )

                async def do_question_research():
                    print(
                        "CLICK: do_question_research",
                        flush=True,
                    )

                    current_company = (
                        profile.target_company
                    )

                    current_role = (
                        profile.target_role
                    )

                    if (
                        not current_company
                        or not current_role
                    ):
                        ui.notify(
                            "Set your target first.",
                            type="warning",
                        )
                        return

                    ui.notify(
                        (
                            "Searching current "
                            "interview information..."
                        )
                    )

                    def work():
                        local_db = (
                            db_session()
                        )

                        try:
                            research_questions(
                                local_db,
                                current_company,
                                current_role,
                            )

                        finally:
                            local_db.close()

                    try:
                        await run.io_bound(
                            work
                        )

                        ui.notify(
                            (
                                "Internet research "
                                "completed."
                            ),
                            type="positive",
                        )

                        ui.navigate.to(
                            "/student"
                        )

                    except Exception as exc:
                        ui.notify(
                            f"Search failed: {exc}",
                            type="negative",
                        )

                ui.button(
                    (
                        "Search current "
                        "tagged/interview questions"
                    ),
                    on_click=(
                        do_question_research
                    ),
                )

                latest_research = None

                if (
                    profile.target_company
                    and profile.target_role
                ):
                    latest_research = (
                        db.scalar(
                            select(
                                QuestionResearch
                            )
                            .where(
                                QuestionResearch
                                .company_name
                                == profile
                                .target_company,

                                QuestionResearch
                                .role_name
                                == profile
                                .target_role,
                            )
                            .order_by(
                                QuestionResearch
                                .created_at
                                .desc()
                            )
                        )
                    )

                if latest_research:
                    with ui.card().classes(
                        "w-full"
                    ):
                        ui.label(
                            "Recurring topics"
                        ).classes(
                            "font-semibold"
                        )

                        for topic in (
                            latest_research
                            .recurring_topics
                        ):
                            ui.label(
                                f"• {topic}"
                            )

                        ui.label(
                            (
                                "Question/problem titles "
                                "found in sources"
                            )
                        ).classes(
                            "font-semibold mt-3"
                        )

                        for title in (
                            latest_research
                            .notable_question_titles
                        ):
                            ui.label(
                                f"• {title}"
                            )

                        ui.label(
                            "Sources"
                        ).classes(
                            "font-semibold mt-3"
                        )

                        for source in (
                            latest_research.sources
                        ):
                            if source.get(
                                "url"
                            ):
                                ui.link(
                                    (
                                        source.get(
                                            "title"
                                        )
                                        or source[
                                            "url"
                                        ]
                                    ),
                                    source["url"],
                                    new_tab=True,
                                )

            with ui.column().classes("w-full gap-4") as assessments_panel:
                section_heading("Coding & Aptitude Assessments", "Generate role-specific assessments and review or reopen previous attempts.")
                ui.separator()

                ui.label(
                    "Assessments"
                ).classes(
                    "text-2xl font-semibold"
                )

                async def generate_coding():
                    print(
                        "CLICK: generate_coding",
                        flush=True,
                    )

                    client = ui.context.client
                    current_company = profile.target_company
                    current_role = profile.target_role
                    student_id = user.id

                    if (
                        not current_company
                        or not current_role
                    ):
                        with client:
                            ui.notify(
                                "Set your target first.",
                                type="warning",
                            )
                        return

                    with client:
                        ui.notify(
                            "Generating coding assessment..."
                        )

                    def work():
                        local_db = db_session()

                        try:
                            print(
                                (
                                    "STEP: creating coding assessment for "
                                    f"student={student_id}, "
                                    f"company={current_company}, "
                                    f"role={current_role}"
                                ),
                                flush=True,
                            )

                            assessment = create_coding_assessment(
                                local_db,
                                student_id,
                                current_company,
                                current_role,
                            )

                            print(
                                (
                                    "STEP: coding assessment created "
                                    f"session_id={assessment.id}"
                                ),
                                flush=True,
                            )

                            return assessment.id

                        finally:
                            local_db.close()

                    try:
                        session_id = await run.io_bound(
                            work
                        )

                        with client:
                            ui.navigate.to(
                                f"/assessment/{session_id}"
                            )

                    except Exception as exc:
                        print(
                            f"ERROR generate_coding: {exc!r}",
                            flush=True,
                        )

                        with client:
                            ui.notify(
                                (
                                    "Could not generate assessment: "
                                    f"{exc}"
                                ),
                                type="negative",
                            )

                async def generate_aptitude():
                    print(
                        "CLICK: generate_aptitude",
                        flush=True,
                    )

                    client = ui.context.client
                    current_company = profile.target_company
                    current_role = profile.target_role
                    student_id = user.id

                    if (
                        not current_company
                        or not current_role
                    ):
                        with client:
                            ui.notify(
                                "Set your target first.",
                                type="warning",
                            )
                        return

                    with client:
                        ui.notify(
                            "Generating aptitude assessment..."
                        )

                    def work():
                        local_db = db_session()

                        try:
                            print(
                                (
                                    "STEP: creating aptitude assessment for "
                                    f"student={student_id}, "
                                    f"company={current_company}, "
                                    f"role={current_role}"
                                ),
                                flush=True,
                            )

                            assessment = create_aptitude_assessment(
                                local_db,
                                student_id,
                                current_company,
                                current_role,
                            )

                            print(
                                (
                                    "STEP: aptitude assessment created "
                                    f"session_id={assessment.id}"
                                ),
                                flush=True,
                            )

                            return assessment.id

                        finally:
                            local_db.close()

                    try:
                        session_id = await run.io_bound(
                            work
                        )

                        with client:
                            ui.navigate.to(
                                f"/assessment/{session_id}"
                            )

                    except Exception as exc:
                        print(
                            f"ERROR generate_aptitude: {exc!r}",
                            flush=True,
                        )

                        with client:
                            ui.notify(
                                (
                                    "Could not generate aptitude assessment: "
                                    f"{exc}"
                                ),
                                type="negative",
                            )

                with ui.row():
                    ui.button(
                        "Generate coding assessment",
                        on_click=generate_coding,
                    )

                    ui.button(
                        "Generate aptitude assessment",
                        on_click=generate_aptitude,
                    )

                if sessions:
                    assessment_rows = [
                        {
                            "id": item.id,
                            "type": (
                                item.kind.value
                                .title()
                            ),
                            "status": (
                                item.status.value
                                .replace(
                                    "_",
                                    " ",
                                )
                                .title()
                            ),
                            "score": (
                                f"{item.score:.1f}%"
                                if item.score
                                is not None
                                else ""
                            ),
                        }
                        for item in sessions
                    ]

                    ui.table(
                        columns=[
                            {
                                "name": "id",
                                "label": "ID",
                                "field": "id",
                            },
                            {
                                "name": "type",
                                "label": "Type",
                                "field": "type",
                            },
                            {
                                "name": "status",
                                "label": "Status",
                                "field": "status",
                            },
                            {
                                "name": "score",
                                "label": "Score",
                                "field": "score",
                            },
                        ],
                        rows=assessment_rows,
                        row_key="id",
                    )

                    ui.label("Assessment to open").classes("font-medium text-slate-700")
                    session_picker = ui.select(
                        {item.id: f"{item.kind.value.title()} #{item.id}" for item in sessions},
                        label="Select an assessment",
                    ).props("outlined options-dense").classes("w-full max-w-xl")

                    ui.button(
                        "Open",
                        on_click=lambda:
                            ui.navigate.to(
                                (
                                    f"/assessment/"
                                    f"{session_picker.value}"
                                    if session_picker.value
                                    else "/student"
                                )
                            ),
                    )

            with ui.column().classes("w-full gap-4") as mock_panel:
                section_heading("AI Mock Interview", "Generate and complete a mock interview personalized to your role and resume.")
                ui.separator()

                ui.label(
                    "AI mock interview"
                ).classes(
                    "text-2xl font-semibold"
                )

                ui.label("Mock interview type").classes("font-medium text-slate-700")
                interview_type = ui.select(
                    {
                        InterviewType.GENERAL.value: "General interview",
                        InterviewType.PROJECT.value: "Project depth interview",
                        InterviewType.BEHAVIORAL.value: "Behavioral interview",
                    },
                    value=InterviewType.GENERAL.value,
                    label="Select interview type",
                ).props("outlined options-dense").classes("w-full max-w-xl")

                async def generate_mock():
                    print(
                        "CLICK: generate_mock",
                        flush=True,
                    )

                    current_company = (
                        profile.target_company
                    )

                    current_role = (
                        profile.target_role
                    )

                    selected_type = (
                        interview_type.value
                    )

                    if (
                        not current_company
                        or not current_role
                    ):
                        ui.notify(
                            "Set your target first.",
                            type="warning",
                        )
                        return

                    if not latest_resume:
                        ui.notify(
                            (
                                "Upload and analyze "
                                "a resume first."
                            ),
                            type="warning",
                        )
                        return

                    ui.notify(
                        (
                            "Generating mock "
                            "interview..."
                        )
                    )

                    def work():
                        local_db = (
                            db_session()
                        )

                        try:
                            local_profile = (
                                student_profile_for(
                                    local_db,
                                    user.id,
                                )
                            )

                            local_resume = (
                                latest_resume_for(
                                    local_db,
                                    user.id,
                                )
                            )

                            role_profile = (
                                get_role_profile(
                                    local_db,
                                    local_profile
                                    .target_company,
                                    local_profile
                                    .target_role,
                                )
                            )

                            role_data = None

                            if role_profile:
                                role_data = {
                                    "process_summary":
                                        role_profile
                                        .process_summary,
                                    "weights":
                                        role_profile
                                        .weights,
                                    "thresholds":
                                        role_profile
                                        .thresholds,
                                }

                            previous_mocks = (
                                local_db.scalars(
                                    select(
                                        MockInterview
                                    )
                                    .where(
                                        MockInterview.student_id
                                        == user.id,

                                        MockInterview.company_name
                                        == local_profile.target_company,

                                        MockInterview.role_name
                                        == local_profile.target_role,

                                        MockInterview.interview_type
                                        == InterviewType(
                                            selected_type
                                        ),
                                    )
                                    .order_by(
                                        MockInterview.created_at.desc()
                                    )
                                    .limit(
                                        10
                                    )
                                ).all()
                            )

                            previous_questions = []

                            for previous_mock in previous_mocks:
                                for previous_question in (
                                    previous_mock.questions
                                    or []
                                ):
                                    if previous_question:
                                        previous_questions.append(
                                            previous_question
                                        )

                            previous_questions = (
                                previous_questions[:40]
                            )

                            print(
                                (
                                    "STEP: passing "
                                    f"{len(previous_questions)} "
                                    "previous mock questions "
                                    "to Ollama for deduplication"
                                ),
                                flush=True,
                            )

                            output = (
                                llm_service
                                .generate_mock_interview(
                                    company=(
                                        local_profile
                                        .target_company
                                    ),
                                    role=(
                                        local_profile
                                        .target_role
                                    ),
                                    interview_type=(
                                        selected_type
                                    ),
                                    resume_text=(
                                        local_resume
                                        .extracted_text
                                    ),
                                    role_profile=(
                                        role_data
                                    ),
                                    previous_questions=(
                                        previous_questions
                                    ),
                                )
                            )

                            record = (
                                MockInterview(
                                    student_id=user.id,
                                    interview_type=(
                                        InterviewType(
                                            selected_type
                                        )
                                    ),
                                    company_name=(
                                        local_profile
                                        .target_company
                                    ),
                                    role_name=(
                                        local_profile
                                        .target_role
                                    ),
                                    questions=(
                                        output.questions
                                    ),
                                )
                            )

                            local_db.add(
                                record
                            )

                            local_db.commit()

                            local_db.refresh(
                                record
                            )

                            return record.id

                        finally:
                            local_db.close()

                    try:
                        mock_id = (
                            await run.io_bound(
                                work
                            )
                        )

                        ui.navigate.to(
                            f"/mock/{mock_id}"
                        )

                    except Exception as exc:
                        ui.notify(
                            (
                                "Could not generate "
                                f"interview: {exc}"
                            ),
                            type="negative",
                        )

                ui.button(
                    "Generate mock interview",
                    on_click=generate_mock,
                )

                if mocks:
                    ui.label("Previous mock interview").classes("font-medium text-slate-700")
                    picker = ui.select(
                        {item.id: f"{item.interview_type.value.title()} #{item.id}" for item in mocks},
                        label="Select a previous mock interview",
                    ).props("outlined options-dense").classes("w-full max-w-xl")

                    ui.button(
                        "Open mock interview",
                        on_click=lambda:
                            ui.navigate.to(
                                (
                                    f"/mock/{picker.value}"
                                    if picker.value
                                    else "/student"
                                )
                            ),
                    )

            with ui.column().classes("w-full gap-4") as interventions_panel:
                section_heading("Two-Week Intervention Plan", "Generate focused practice plans based on your current readiness bottleneck.")
                ui.separator()

                ui.label(
                    "Two-week intervention plan"
                ).classes(
                    "text-2xl font-semibold"
                )

                async def generate_plan():
                    print(
                        "CLICK: generate_plan",
                        flush=True,
                    )

                    current_company = (
                        profile.target_company
                    )

                    current_role = (
                        profile.target_role
                    )

                    if (
                        not current_company
                        or not current_role
                    ):
                        ui.notify(
                            "Set target first.",
                            type="warning",
                        )
                        return

                    ui.notify(
                        (
                            "Generating intervention "
                            "plan..."
                        )
                    )

                    def work():
                        local_db = (
                            db_session()
                        )

                        try:
                            return (
                                create_intervention(
                                    local_db,
                                    user.id,
                                    current_company,
                                    current_role,
                                    None,
                                ).id
                            )

                        finally:
                            local_db.close()

                    try:
                        await run.io_bound(
                            work
                        )

                        ui.notify(
                            (
                                "Intervention plan "
                                "created."
                            ),
                            type="positive",
                        )

                        ui.navigate.to(
                            "/student"
                        )

                    except Exception as exc:
                        ui.notify(
                            str(exc),
                            type="negative",
                        )

                ui.button(
                    "Generate next intervention",
                    on_click=generate_plan,
                )

                for item in interventions:
                    with ui.card().classes(
                        "w-full"
                    ):
                        ui.label(
                            item.title
                        ).classes(
                            "font-bold"
                        )

                        ui.label(
                            item.dimension.value
                            .replace(
                                "_",
                                " ",
                            )
                            .title()
                        )

                        ui.markdown(
                            item.plan
                        )

            with ui.column().classes("w-full gap-4") as outcomes_panel:
                section_heading("Placement Outcomes", "Record real application and interview stages so outcomes can be tracked alongside readiness.")
                ui.separator()

                ui.label(
                    "Placement / interview outcome"
                ).classes(
                    "text-2xl font-semibold"
                )

                outcome_company = ui.input("Company name").props("outlined").classes("w-full max-w-xl")

                outcome_role = ui.input("Role name").props("outlined").classes("w-full max-w-xl")

                ui.label("Recruitment stage").classes("font-medium text-slate-700")
                outcome_stage = ui.select(
                    {stage.value: stage.value.replace("_", " ").title() for stage in PlacementStage},
                    label="Select recruitment stage",
                ).props("outlined options-dense").classes("w-full max-w-xl")

                ui.label("Stage result").classes("font-medium text-slate-700 mt-2")
                outcome_result = ui.select(
                    {result.value: result.value.title() for result in PlacementResult},
                    label="Select result",
                ).props("outlined options-dense").classes("w-full max-w-xl")

                outcome_notes = ui.textarea("Additional notes").props("outlined").classes("w-full max-w-2xl")

                def save_outcome():
                    if (
                        not outcome_company.value
                        or not outcome_role.value
                        or not outcome_stage.value
                        or not outcome_result.value
                    ):
                        ui.notify(
                            (
                                "Complete all required "
                                "outcome fields."
                            ),
                            type="warning",
                        )
                        return

                    local_db = (
                        db_session()
                    )

                    try:
                        local_db.add(
                            PlacementOutcome(
                                student_id=user.id,
                                company_name=(
                                    clean_target(
                                        outcome_company
                                        .value
                                    )
                                ),
                                role_name=(
                                    clean_target(
                                        outcome_role
                                        .value
                                    )
                                ),
                                stage=(
                                    PlacementStage(
                                        outcome_stage
                                        .value
                                    )
                                ),
                                result=(
                                    PlacementResult(
                                        outcome_result
                                        .value
                                    )
                                ),
                                notes=(
                                    clean_target(
                                        outcome_notes
                                        .value
                                    )
                                    or None
                                ),
                            )
                        )

                        local_db.commit()

                        ui.notify(
                            "Outcome recorded.",
                            type="positive",
                        )

                    finally:
                        local_db.close()

                ui.button(
                    "Record outcome",
                    on_click=save_outcome,
                )

            with ui.column().classes("w-full gap-4") as analytics_panel:
                section_heading(
                    "Placement Analytics",
                    "Review your readiness progress and recruitment progress.",
                )
                ui.separator()

                with ui.row().classes("w-full items-end gap-4 flex-wrap"):
                    student_readiness_filter = ui.select(
                        TABLEAU_READINESS_AREAS,
                        value=TABLEAU_ALL,
                        label="Readiness area",
                    ).props(
                        "outlined options-dense"
                    ).classes(
                        "w-full max-w-sm"
                    )

                student_tableau = ui.html(
                    tableau_iframe(
                        tableau_view_url(
                            TABLEAU_STUDENT_URL,
                            {
                                "Student Name": user.full_name,
                            },
                        ),
                        height=1200,
                    ),
                    sanitize=False,
                ).classes("w-full")

                def update_student_tableau():
                    filters = {
                        "Student Name": user.full_name,
                    }

                    if student_readiness_filter.value != TABLEAU_ALL:
                        filters["Readiness Area"] = student_readiness_filter.value

                    student_tableau.set_content(
                        tableau_iframe(
                            tableau_view_url(
                                TABLEAU_STUDENT_URL,
                                filters,
                            ),
                            height=1200,
                        )
                    )

                student_readiness_filter.on(
                    "update:model-value",
                    lambda _: update_student_tableau(),
                )


            target_panel.set_visibility(False)
            resume_panel.set_visibility(False)
            research_panel.set_visibility(False)
            assessments_panel.set_visibility(False)
            mock_panel.set_visibility(False)
            interventions_panel.set_visibility(False)
            outcomes_panel.set_visibility(False)
            analytics_panel.set_visibility(False)
    finally:
        db.close()


@ui.page("/assessment/{session_id}")
def assessment_page(
    session_id: int,
):
    user = require_role(
        UserRole.STUDENT
    )

    if not user:
        return

    navigation(
        user
    )

    db = db_session()

    try:
        session = db.get(
            AssessmentSession,
            session_id,
        )

        if (
            not session
            or session.student_id
            != user.id
        ):
            ui.label(
                "Assessment not found."
            )
            return

        questions = (
            db.scalars(
                select(
                    AssessmentQuestion
                )
                .where(
                    AssessmentQuestion.session_id
                    == session.id
                )
                .order_by(
                    AssessmentQuestion.position
                )
            ).all()
        )

        question_ids = [
            item.id
            for item
            in questions
        ]

        existing = []

        if question_ids:
            existing = (
                db.scalars(
                    select(
                        AssessmentResponse
                    )
                    .where(
                        AssessmentResponse.student_id
                        == user.id,

                        AssessmentResponse.question_id
                        .in_(
                            question_ids
                        ),
                    )
                ).all()
            )

        existing_by_question = {
            item.question_id:
                item
            for item
            in existing
        }

        with ui.column().classes(
            "w-full max-w-5xl mx-auto p-6 gap-6"
        ):
            heading(
                (
                    f"{session.kind.value.title()} "
                    "assessment"
                ),
                (
                    f"{session.company_name} — "
                    f"{session.role_name}"
                ),
            )

            if (
                session.status
                == AssessmentStatus.COMPLETED
            ):
                ui.label(
                    (
                        "Completed: "
                        f"{session.score:.1f}%"
                    )
                ).classes(
                    "text-2xl font-bold"
                )

            for question in questions:
                with ui.card().classes(
                    "w-full"
                ):
                    ui.label(
                        (
                            f"{question.position}. "
                            f"{question.title}"
                        )
                    ).classes(
                        "text-xl font-semibold"
                    )

                    ui.label(
                        (
                            f"{question.topic} • "
                            f"{question.difficulty}"
                        )
                    ).classes(
                        "text-gray-500"
                    )

                    ui.markdown(
                        question.prompt
                    )

                    if (
                        question.id
                        in existing_by_question
                    ):
                        response = (
                            existing_by_question[
                                question.id
                            ]
                        )

                        ui.label(
                            (
                                "Submitted — score "
                                f"{response.score:.0f}%"
                            )
                        ).classes(
                            "font-semibold"
                        )

                        if response.feedback:
                            ui.label(
                                response.feedback
                            )

                        continue

                    if (
                        session.kind
                        == AssessmentKind.CODING
                    ):
                        code = (
                            ui.textarea(
                                "Python solution",
                                value=(
                                    question
                                    .starter_code
                                    or ""
                                ),
                            ).classes(
                                "w-full font-mono"
                            )
                        )

                        async def submit_code(
                            q=question,
                            code_field=code,
                        ):
                            submitted_code = (
                                code_field.value
                                or ""
                            )

                            if (
                                not submitted_code
                                .strip()
                            ):
                                ui.notify(
                                    "Enter code first.",
                                    type="warning",
                                )
                                return

                            question_id = q.id

                            def work():
                                local_db = (
                                    db_session()
                                )

                                try:
                                    local_q = (
                                        local_db.get(
                                            AssessmentQuestion,
                                            question_id,
                                        )
                                    )

                                    return (
                                        save_coding_response(
                                            local_db,
                                            user.id,
                                            local_q,
                                            submitted_code,
                                        ).score
                                    )

                                finally:
                                    local_db.close()

                            try:
                                score = (
                                    await run.io_bound(
                                        work
                                    )
                                )

                                ui.notify(
                                    (
                                        "Submitted. "
                                        "Test score: "
                                        f"{score:.0f}%"
                                    ),
                                    type="positive",
                                )

                                ui.navigate.to(
                                    (
                                        f"/assessment/"
                                        f"{session_id}"
                                    )
                                )

                            except Exception as exc:
                                ui.notify(
                                    (
                                        "Execution failed: "
                                        f"{exc}"
                                    ),
                                    type="negative",
                                )

                        ui.button(
                            (
                                "Run hidden tests "
                                "and submit"
                            ),
                            on_click=submit_code,
                        )

                    else:
                        option_map = {
                            index: choice
                            for index, choice
                            in enumerate(
                                question.choices
                                or []
                            )
                        }

                        selected = (
                            ui.radio(
                                option_map
                            )
                        )

                        def submit_mcq(
                            q=question,
                            field=selected,
                        ):
                            if (
                                field.value
                                is None
                            ):
                                ui.notify(
                                    "Choose an answer.",
                                    type="warning",
                                )
                                return

                            local_db = (
                                db_session()
                            )

                            try:
                                local_q = (
                                    local_db.get(
                                        AssessmentQuestion,
                                        q.id,
                                    )
                                )

                                response = (
                                    save_aptitude_response(
                                        local_db,
                                        user.id,
                                        local_q,
                                        int(
                                            field.value
                                        ),
                                    )
                                )

                                ui.notify(
                                    (
                                        "Correct."
                                        if response.score
                                        == 100
                                        else "Incorrect."
                                    )
                                )

                                ui.navigate.to(
                                    (
                                        f"/assessment/"
                                        f"{session_id}"
                                    )
                                )

                            finally:
                                local_db.close()

                        ui.button(
                            "Submit answer",
                            on_click=submit_mcq,
                        )

            if (
                session.status
                != AssessmentStatus.COMPLETED
            ):

                def complete():
                    local_db = (
                        db_session()
                    )

                    try:
                        try:
                            score = (
                                complete_assessment(
                                    local_db,
                                    session.id,
                                    user.id,
                                )
                            )

                        except ValueError as exc:
                            ui.notify(
                                str(exc),
                                type="warning",
                            )
                            return

                        ui.notify(
                            (
                                "Assessment completed: "
                                f"{score:.1f}%"
                            ),
                            type="positive",
                        )

                        ui.navigate.to(
                            "/student"
                        )

                    finally:
                        local_db.close()

                ui.button(
                    "Complete assessment",
                    on_click=complete,
                )

    finally:
        db.close()


@ui.page("/mock/{mock_id}")
def mock_interview_page(
    mock_id: int,
):
    user = require_role(
        UserRole.STUDENT
    )

    if not user:
        return

    navigation(
        user
    )

    db = db_session()

    try:
        mock = db.get(
            MockInterview,
            mock_id,
        )

        if (
            not mock
            or mock.student_id
            != user.id
        ):
            ui.label(
                "Mock interview not found."
            )
            return

        with ui.column().classes(
            "w-full max-w-5xl mx-auto p-6 gap-6"
        ):
            heading(
                (
                    f"{mock.interview_type.value.title()} "
                    "mock interview"
                ),
                (
                    f"{mock.company_name} — "
                    f"{mock.role_name}"
                ),
            )

            if mock.completed:
                evaluation = (
                    mock.evaluation
                    or {}
                )

                ui.label(
                    (
                        "Communication: "
                        f"{evaluation.get('communication_score', 0):.1f}%"
                    )
                ).classes(
                    "text-xl"
                )

                ui.label(
                    (
                        "Project depth: "
                        f"{evaluation.get('project_depth_score', 0):.1f}%"
                    )
                ).classes(
                    "text-xl"
                )

                ui.label(
                    (
                        "Interview performance: "
                        f"{evaluation.get('interview_score', 0):.1f}%"
                    )
                ).classes(
                    "text-xl"
                )

                ui.markdown(
                    evaluation.get(
                        "overall_feedback",
                        "",
                    )
                )

                return

            answer_fields = []

            for (
                index,
                question,
            ) in enumerate(
                mock.questions,
                start=1,
            ):
                with ui.card().classes(
                    "w-full"
                ):
                    ui.label(
                        f"{index}. {question}"
                    ).classes(
                        "font-semibold"
                    )

                    field = (
                        ui.textarea(
                            "Your answer"
                        ).classes(
                            "w-full"
                        )
                    )

                    answer_fields.append(
                        field
                    )

            async def submit():
                print(
                    "CLICK: submit_mock_interview",
                    flush=True,
                )

                answers = [
                    clean_target(
                        field.value
                    )
                    for field
                    in answer_fields
                ]

                if any(
                    not answer
                    for answer
                    in answers
                ):
                    ui.notify(
                        "Answer every question.",
                        type="warning",
                    )
                    return

                current_mock_id = (
                    mock.id
                )

                def work():
                    local_db = (
                        db_session()
                    )

                    try:
                        local_mock = (
                            local_db.get(
                                MockInterview,
                                current_mock_id,
                            )
                        )

                        resume = (
                            latest_resume_for(
                                local_db,
                                user.id,
                            )
                        )

                        result = (
                            llm_service
                            .evaluate_mock_interview(
                                company=(
                                    local_mock
                                    .company_name
                                ),
                                role=(
                                    local_mock
                                    .role_name
                                ),
                                interview_type=(
                                    local_mock
                                    .interview_type
                                    .value
                                ),
                                questions=(
                                    local_mock
                                    .questions
                                ),
                                answers=answers,
                                resume_text=(
                                    resume
                                    .extracted_text
                                    if resume
                                    else ""
                                ),
                            )
                        )

                        local_mock.answers = (
                            answers
                        )

                        local_mock.evaluation = (
                            result.model_dump()
                        )

                        local_mock.completed = (
                            True
                        )

                        values = [
                            (
                                ReadinessDimension
                                .COMMUNICATION,
                                result
                                .communication_score,
                            ),
                            (
                                ReadinessDimension
                                .PROJECT_DEPTH,
                                result
                                .project_depth_score,
                            ),
                            (
                                ReadinessDimension
                                .INTERVIEW,
                                result
                                .interview_score,
                            ),
                        ]

                        for (
                            dimension,
                            score,
                        ) in values:
                            local_db.add(
                                ReadinessEvidence(
                                    student_id=(
                                        user.id
                                    ),
                                    dimension=(
                                        dimension
                                    ),
                                    score=score,
                                    source=(
                                        EvidenceSource
                                        .LLM
                                    ),
                                    verified=False,
                                    evidence_text=(
                                        result
                                        .overall_feedback
                                    ),
                                    source_entity_type=(
                                        "mock_interview"
                                    ),
                                    source_entity_id=(
                                        local_mock.id
                                    ),
                                )
                            )

                        local_db.commit()

                    finally:
                        local_db.close()

                try:
                    await run.io_bound(
                        work
                    )

                    ui.notify(
                        (
                            "Mock interview "
                            "evaluated."
                        ),
                        type="positive",
                    )

                    ui.navigate.to(
                        (
                            f"/mock/"
                            f"{current_mock_id}"
                        )
                    )

                except Exception as exc:
                    ui.notify(
                        (
                            "Evaluation failed: "
                            f"{exc}"
                        ),
                        type="negative",
                    )

            ui.button(
                "Submit interview",
                on_click=submit,
            )

    finally:
        db.close()


@ui.page("/mentor")
def mentor_page():
    user = require_role(
        UserRole.MENTOR
    )

    if not user:
        return

    navigation(
        user
    )

    db = db_session()

    try:
        now = datetime.now(
            timezone.utc
        )

        week_start_date = (
            now.date()
            - timedelta(
                days=now.weekday()
            )
        )

        week_start_dt = datetime.combine(
            week_start_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )

        week_end_dt = (
            week_start_dt
            + timedelta(days=7)
        )

        capacity_row = db.execute(
            select(
                mentor_weekly_capacity.c.hours_available
            ).where(
                mentor_weekly_capacity.c.mentor_id
                == user.id,
                mentor_weekly_capacity.c.week_start
                == week_start_date,
            )
        ).first()

        weekly_capacity = (
            float(capacity_row[0])
            if capacity_row
            else 0.0
        )

        mentor_sessions = (
            db.scalars(
                select(
                    MentorSession
                )
                .where(
                    MentorSession.mentor_id
                    == user.id,
                    MentorSession.scheduled_for
                    >= week_start_dt,
                    MentorSession.scheduled_for
                    < week_end_dt,
                )
                .order_by(
                    MentorSession.scheduled_for
                )
            ).all()
        )

        scheduled_hours = float(
            len(mentor_sessions)
        )

        remaining_hours = max(
            0.0,
            weekly_capacity
            - scheduled_hours,
        )

        active_assignments = (
            db.scalars(
                select(
                    MentorStudentAssignment
                ).where(
                    MentorStudentAssignment.mentor_id
                    == user.id,
                    MentorStudentAssignment.active
                    .is_(True),
                )
            ).all()
        )

        assigned_student_ids = [
            assignment.student_id
            for assignment
            in active_assignments
        ]

        assigned_students = (
            db.scalars(
                select(
                    User
                )
                .where(
                    User.id.in_(
                        assigned_student_ids
                    ),
                    User.role
                    == UserRole.STUDENT,
                    User.is_active
                    .is_(True),
                )
                .order_by(
                    User.full_name
                )
            ).all()
            if assigned_student_ids
            else []
        )

        already_scheduled_student_ids = set(
            db.scalars(
                select(
                    MentorSession.student_id
                ).where(
                    MentorSession.scheduled_for
                    >= week_start_dt,
                    MentorSession.scheduled_for
                    < week_end_dt,
                )
            ).all()
        )

        ranked_students = []

        for student in assigned_students:
            readiness = (
                get_student_readiness(
                    db,
                    student.id,
                )
            )

            priority = (
                calculate_mentor_priority(
                    db,
                    student.id,
                )
            )

            ranked_students.append(
                {
                    "student": student,
                    "readiness": readiness,
                    "priority": priority,
                }
            )

        ranked_students.sort(
            key=lambda item: (
                item["priority"][
                    "priority_score"
                ]
            ),
            reverse=True,
        )

        eligible_students = [
            item
            for item in ranked_students
            if item["student"].id
            not in already_scheduled_student_ids
        ]

        remaining_slots = int(
            remaining_hours
        )

        recommended_students = (
            eligible_students[
                :remaining_slots
            ]
        )

        scheduled_student_ids_for_mentor = {
            item.student_id
            for item in mentor_sessions
        }

        evaluation_students = list(
            assigned_students
        )

        def show_mentor_section(name):
            sections = {
                "capacity": capacity_panel,
                "priorities": priority_panel,
                "sessions": sessions_panel,
                "evaluations": evaluations_panel,
                "analytics": analytics_panel,
            }
            for section_name, panel in sections.items():
                panel.set_visibility(section_name == name)

        with ui.left_drawer(value=True).props("bordered width=260 breakpoint=700").classes("bg-white px-2 pt-2 pb-3 shadow-sm") as mentor_drawer:
            with ui.row().classes("w-full justify-start items-center mb-2"):
                ui.button(icon="menu", on_click=mentor_drawer.toggle).props("round dense flat color=primary").tooltip("Collapse navigation")
            ui.button("Weekly Capacity", icon="schedule", on_click=lambda: show_mentor_section("capacity")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Student Priority Queue", icon="priority_high", on_click=lambda: show_mentor_section("priorities")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Scheduled Sessions", icon="event", on_click=lambda: show_mentor_section("sessions")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Student Evaluations", icon="rate_review", on_click=lambda: show_mentor_section("evaluations")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Placement Analytics", icon="analytics", on_click=lambda: show_mentor_section("analytics")).props("flat no-caps align=left").classes("w-full justify-start text-left")

        with ui.page_sticky(position="top-left", x_offset=8, y_offset=8):
            mentor_open_button = ui.button(icon="menu", on_click=mentor_drawer.toggle).props("round dense unelevated color=primary").tooltip("Open navigation")
            mentor_open_button.bind_visibility_from(mentor_drawer, "value", backward=lambda value: not value)

        with ui.column().classes(
            "w-full max-w-7xl mx-auto p-6 gap-6"
        ):
            heading(
                "Mentor dashboard",
                (
                    "Set your weekly availability. "
                    "The system ranks only students assigned "
                    "to you by faculty and recommends who "
                    "should receive your remaining mentoring "
                    "hours first."
                ),
            )

            with ui.column().classes("w-full gap-4") as capacity_panel:
                section_heading("Weekly Mentoring Capacity", "Set your available hours for the current week and see scheduled and remaining capacity.")
                ui.label(
                    "Weekly mentoring capacity"
                ).classes(
                    "text-2xl font-semibold"
                )

                with ui.card().classes(
                    "w-full"
                ):
                    ui.label(
                        (
                            "Week of "
                            f"{week_start_date.strftime('%B %d, %Y')}"
                        )
                    ).classes(
                        "font-semibold"
                    )

                    capacity_input = ui.number(
                        "Hours available this week",
                        value=weekly_capacity,
                        min=0,
                        step=1,
                    ).classes(
                        "w-full max-w-md"
                    )

                    def save_capacity():
                        value = float(
                            capacity_input.value
                            or 0
                        )

                        if value < 0:
                            ui.notify(
                                "Weekly hours cannot be negative.",
                                type="warning",
                            )
                            return

                        if value != int(value):
                            ui.notify(
                                (
                                    "Use whole hours for now. "
                                    "Each mentoring session is one hour."
                                ),
                                type="warning",
                            )
                            return

                        local_db = db_session()

                        try:
                            existing = local_db.execute(
                                select(
                                    mentor_weekly_capacity.c.id
                                ).where(
                                    mentor_weekly_capacity.c.mentor_id
                                    == user.id,
                                    mentor_weekly_capacity.c.week_start
                                    == week_start_date,
                                )
                            ).first()

                            if existing:
                                local_db.execute(
                                    mentor_weekly_capacity.update()
                                    .where(
                                        mentor_weekly_capacity.c.id
                                        == existing[0]
                                    )
                                    .values(
                                        hours_available=value
                                    )
                                )
                            else:
                                local_db.execute(
                                    mentor_weekly_capacity.insert()
                                    .values(
                                        mentor_id=user.id,
                                        week_start=week_start_date,
                                        hours_available=value,
                                    )
                                )

                            local_db.commit()

                            ui.notify(
                                "Weekly availability saved.",
                                type="positive",
                            )

                            ui.navigate.to(
                                "/mentor"
                            )

                        except Exception as exc:
                            local_db.rollback()

                            ui.notify(
                                (
                                    "Could not save availability: "
                                    f"{exc}"
                                ),
                                type="negative",
                            )

                        finally:
                            local_db.close()

                    ui.button(
                        "Save weekly availability",
                        on_click=save_capacity,
                    )

                with ui.row().classes(
                    "w-full gap-4 flex-wrap"
                ):
                    with ui.card().classes(
                        "min-w-56 flex-1"
                    ):
                        ui.label(
                            "Available"
                        )
                        ui.label(
                            f"{weekly_capacity:.0f} hrs"
                        ).classes(
                            "text-3xl font-bold"
                        )

                    with ui.card().classes(
                        "min-w-56 flex-1"
                    ):
                        ui.label(
                            "Scheduled"
                        )
                        ui.label(
                            f"{scheduled_hours:.0f} hrs"
                        ).classes(
                            "text-3xl font-bold"
                        )

                    with ui.card().classes(
                        "min-w-56 flex-1"
                    ):
                        ui.label(
                            "Remaining"
                        )
                        ui.label(
                            f"{remaining_hours:.0f} hrs"
                        ).classes(
                            "text-3xl font-bold"
                        )

            with ui.column().classes("w-full gap-4") as priority_panel:
                section_heading("Student Priority Queue", "Review assigned students who should receive your remaining mentor time first.")
                ui.separator()

                ui.label(
                    "Students to attend to this week"
                ).classes(
                    "text-2xl font-semibold"
                )

                if weekly_capacity <= 0:
                    ui.label(
                        (
                            "Enter your available mentoring hours "
                            "for this week to receive a priority queue."
                        )
                    ).classes(
                        "text-gray-600"
                    )

                elif remaining_slots <= 0:
                    ui.label(
                        (
                            "Your mentoring capacity for this week "
                            "has already been fully allocated."
                        )
                    ).classes(
                        "text-gray-600"
                    )

                elif not recommended_students:
                    ui.label(
                        (
                            "There are no unallocated students "
                            "requiring a session this week."
                        )
                    ).classes(
                        "text-gray-600"
                    )

                else:
                    for rank, item in enumerate(
                        recommended_students,
                        start=1,
                    ):
                        student = item[
                            "student"
                        ]
                        readiness = item[
                            "readiness"
                        ]
                        priority = item[
                            "priority"
                        ]

                        with ui.card().classes(
                            "w-full"
                        ):
                            ui.label(
                                (
                                    f"#{rank} — "
                                    f"{student.full_name}"
                                )
                            ).classes(
                                "text-xl font-semibold"
                            )

                            with ui.row().classes(
                                "w-full gap-6 flex-wrap"
                            ):
                                ui.label(
                                    (
                                        "Readiness: "
                                        f"{readiness['overall_score']:.1f}%"
                                        if readiness[
                                            "overall_score"
                                        ] is not None
                                        else "Readiness: Unknown"
                                    )
                                )

                                ui.label(
                                    (
                                        "Bottleneck: "
                                        + (
                                            readiness[
                                                "bottleneck"
                                            ]
                                            .replace(
                                                "_",
                                                " ",
                                            )
                                            .title()
                                            if readiness[
                                                "bottleneck"
                                            ]
                                            else "Unknown"
                                        )
                                    )
                                )

                                ui.label(
                                    (
                                        "Priority: "
                                        f"{priority['priority_score']}"
                                    )
                                )

                            ui.label(
                                "Recommended allocation: 1 hour"
                            ).classes(
                                "text-gray-600"
                            )

                            date_input = ui.input(
                                "Date",
                                placeholder="YYYY-MM-DD",
                            ).classes(
                                "w-full max-w-sm"
                            )

                            time_input = ui.input(
                                "Time",
                                placeholder="HH:MM",
                            ).classes(
                                "w-full max-w-sm"
                            )

                            notes_input = ui.textarea(
                                "Session notes"
                            ).classes(
                                "w-full"
                            )

                            def schedule_recommended(
                                student_id=student.id,
                                date_field=date_input,
                                time_field=time_input,
                                notes_field=notes_input,
                            ):
                                if (
                                    not date_field.value
                                    or not time_field.value
                                ):
                                    ui.notify(
                                        "Date and time are required.",
                                        type="warning",
                                    )
                                    return

                                try:
                                    scheduled = (
                                        datetime
                                        .fromisoformat(
                                            (
                                                f"{date_field.value}"
                                                f"T{time_field.value}"
                                            )
                                        )
                                        .replace(
                                            tzinfo=timezone.utc
                                        )
                                    )

                                except ValueError:
                                    ui.notify(
                                        "Invalid date or time.",
                                        type="negative",
                                    )
                                    return

                                if not (
                                    week_start_dt
                                    <= scheduled
                                    < week_end_dt
                                ):
                                    ui.notify(
                                        (
                                            "Choose a date within the "
                                            "current mentoring week."
                                        ),
                                        type="warning",
                                    )
                                    return

                                if scheduled < now:
                                    ui.notify(
                                        "Choose a future time.",
                                        type="warning",
                                    )
                                    return

                                local_db = db_session()

                                try:
                                    current_capacity_row = (
                                        local_db.execute(
                                            select(
                                                mentor_weekly_capacity
                                                .c.hours_available
                                            ).where(
                                                mentor_weekly_capacity
                                                .c.mentor_id
                                                == user.id,
                                                mentor_weekly_capacity
                                                .c.week_start
                                                == week_start_date,
                                            )
                                        ).first()
                                    )

                                    current_capacity = (
                                        float(
                                            current_capacity_row[0]
                                        )
                                        if current_capacity_row
                                        else 0.0
                                    )

                                    current_session_count = (
                                        local_db.scalar(
                                            select(
                                                func.count(
                                                    MentorSession.id
                                                )
                                            ).where(
                                                MentorSession.mentor_id
                                                == user.id,
                                                MentorSession.scheduled_for
                                                >= week_start_dt,
                                                MentorSession.scheduled_for
                                                < week_end_dt,
                                            )
                                        )
                                        or 0
                                    )

                                    if (
                                        current_session_count
                                        >= current_capacity
                                    ):
                                        ui.notify(
                                            (
                                                "Your weekly mentoring "
                                                "capacity has been reached."
                                            ),
                                            type="warning",
                                        )
                                        return

                                    existing_student_session = (
                                        local_db.scalar(
                                            select(
                                                MentorSession
                                            ).where(
                                                MentorSession.student_id
                                                == student_id,
                                                MentorSession.scheduled_for
                                                >= week_start_dt,
                                                MentorSession.scheduled_for
                                                < week_end_dt,
                                            )
                                        )
                                    )

                                    if existing_student_session:
                                        ui.notify(
                                            (
                                                "This student has already "
                                                "been allocated mentor time "
                                                "this week."
                                            ),
                                            type="warning",
                                        )
                                        return

                                    local_db.add(
                                        MentorSession(
                                            student_id=student_id,
                                            mentor_id=user.id,
                                            scheduled_for=scheduled,
                                            notes=(
                                                clean_target(
                                                    notes_field.value
                                                )
                                                or None
                                            ),
                                        )
                                    )

                                    local_db.commit()

                                    ui.notify(
                                        "Mentor session scheduled.",
                                        type="positive",
                                    )

                                    ui.navigate.to(
                                        "/mentor"
                                    )

                                except Exception as exc:
                                    local_db.rollback()

                                    ui.notify(
                                        (
                                            "Could not schedule session: "
                                            f"{exc}"
                                        ),
                                        type="negative",
                                    )

                                finally:
                                    local_db.close()

                            ui.button(
                                "Allocate date and time",
                                on_click=schedule_recommended,
                            )

            with ui.column().classes("w-full gap-4") as sessions_panel:
                section_heading("Scheduled Sessions", "Review and manage the mentor sessions already scheduled for this week.")
                ui.separator()

                ui.label(
                    "Upcoming mentor sessions"
                ).classes(
                    "text-2xl font-semibold"
                )

                if not mentor_sessions:
                    ui.label(
                        "No sessions scheduled for this week."
                    ).classes(
                        "text-gray-600"
                    )

                else:
                    for mentor_session in mentor_sessions:
                        student = db.get(
                            User,
                            mentor_session.student_id,
                        )

                        with ui.card().classes(
                            "w-full"
                        ):
                            with ui.row().classes(
                                "w-full items-center justify-between"
                            ):
                                with ui.column():
                                    ui.label(
                                        (
                                            student.full_name
                                            if student
                                            else "Student"
                                        )
                                    ).classes(
                                        "text-lg font-semibold"
                                    )

                                    ui.label(
                                        mentor_session
                                        .scheduled_for
                                        .strftime(
                                            "%B %d, %Y at %I:%M %p"
                                        )
                                    )

                                    if mentor_session.notes:
                                        ui.label(
                                            mentor_session.notes
                                        ).classes(
                                            "text-gray-600"
                                        )

                                def cancel_session(
                                    session_id=mentor_session.id,
                                ):
                                    local_db = db_session()

                                    try:
                                        session_to_cancel = (
                                            local_db.get(
                                                MentorSession,
                                                session_id,
                                            )
                                        )

                                        if not session_to_cancel:
                                            ui.notify(
                                                "Session no longer exists.",
                                                type="warning",
                                            )
                                            return

                                        if (
                                            session_to_cancel.mentor_id
                                            != user.id
                                        ):
                                            ui.notify(
                                                (
                                                    "You cannot cancel "
                                                    "this session."
                                                ),
                                                type="negative",
                                            )
                                            return

                                        local_db.delete(
                                            session_to_cancel
                                        )

                                        local_db.commit()

                                        ui.notify(
                                            "Session cancelled.",
                                            type="positive",
                                        )

                                        ui.navigate.to(
                                            "/mentor"
                                        )

                                    except Exception as exc:
                                        local_db.rollback()

                                        ui.notify(
                                            (
                                                "Could not cancel session: "
                                                f"{exc}"
                                            ),
                                            type="negative",
                                        )

                                    finally:
                                        local_db.close()

                                ui.button(
                                    "Cancel",
                                    icon="cancel",
                                    on_click=cancel_session,
                                ).props(
                                    "outline color=negative"
                                )

            with ui.column().classes("w-full gap-4") as evaluations_panel:
                section_heading("Student Evaluations", "Record verified mentor evidence for assigned students.")
                ui.separator()

                ui.label(
                    "Record mentor evaluation"
                ).classes(
                    "text-2xl font-semibold"
                )

                if not evaluation_students:
                    ui.label(
                        (
                            "Schedule a student for this week "
                            "before recording a mentor evaluation."
                        )
                    ).classes(
                        "text-gray-600"
                    )

                else:
                    options = {
                        student.id: student.full_name
                        for student in evaluation_students
                    }

                    ui.label("Student to evaluate").classes("font-medium text-slate-700")
                    eval_student = ui.select(options, label="Select student").props("outlined options-dense").classes("w-full max-w-xl")

                    ui.label("Readiness dimension").classes("font-medium text-slate-700 mt-2")
                    eval_dimension = ui.select(
                        {
                            ReadinessDimension.COACHABILITY.value: "Coachability",
                            ReadinessDimension.COMMUNICATION.value: "Communication",
                            ReadinessDimension.INTERVIEW.value: "Interview",
                            ReadinessDimension.PROJECT_DEPTH.value: "Project depth",
                        },
                        label="Select readiness dimension",
                    ).props("outlined options-dense").classes("w-full max-w-xl")

                    eval_score = ui.number(
                        "Score",
                        min=0,
                        max=100,
                    )

                    eval_notes = ui.textarea(
                        "Evidence / notes"
                    )

                    def save_evaluation():
                        if (
                            not eval_student.value
                            or not eval_dimension.value
                            or eval_score.value
                            is None
                        ):
                            ui.notify(
                                "Complete all required fields.",
                                type="warning",
                            )
                            return

                        local_db = db_session()

                        try:
                            local_db.add(
                                ReadinessEvidence(
                                    student_id=int(
                                        eval_student.value
                                    ),
                                    dimension=(
                                        ReadinessDimension(
                                            eval_dimension.value
                                        )
                                    ),
                                    score=float(
                                        eval_score.value
                                    ),
                                    source=(
                                        EvidenceSource.MENTOR
                                    ),
                                    verified=True,
                                    evidence_text=(
                                        clean_target(
                                            eval_notes.value
                                        )
                                        or None
                                    ),
                                    evaluator_id=user.id,
                                )
                            )

                            local_db.commit()

                            ui.notify(
                                "Evaluation recorded.",
                                type="positive",
                            )

                        finally:
                            local_db.close()

                    ui.button(
                        "Save evaluation",
                        on_click=save_evaluation,
                    )

            with ui.column().classes("w-full gap-4") as analytics_panel:
                section_heading(
                    "Placement Analytics",
                    "Review readiness and recruitment outcomes for students assigned to you.",
                )
                ui.separator()

                mentor_student_options = {
                    TABLEAU_ALL: "All assigned students",
                    **{
                        str(student.id): student.full_name
                        for student in assigned_students
                    },
                }

                mentor_students_by_id = {
                    str(student.id): student
                    for student in assigned_students
                }

                with ui.row().classes("w-full items-end gap-4 flex-wrap"):
                    mentor_student_filter = ui.select(
                        mentor_student_options,
                        value=TABLEAU_ALL,
                        label="Student",
                    ).props(
                        "outlined options-dense"
                    ).classes(
                        "w-full max-w-sm"
                    )

                    mentor_readiness_filter = ui.select(
                        TABLEAU_READINESS_AREAS,
                        value=TABLEAU_ALL,
                        label="Readiness area",
                    ).props(
                        "outlined options-dense"
                    ).classes(
                        "w-full max-w-sm"
                    )

                mentor_tableau = ui.html(
                    tableau_iframe(
                        tableau_view_url(
                            TABLEAU_MENTOR_URL,
                            {
                                "Mentor Name": user.full_name,
                            },
                        ),
                        height=1200,
                    ),
                    sanitize=False,
                ).classes("w-full")

                def update_mentor_tableau():
                    filters = {
                        "Mentor Name": user.full_name,
                    }

                    selected_student = mentor_students_by_id.get(
                        str(mentor_student_filter.value)
                    )

                    if selected_student:
                        filters["Student Name"] = selected_student.full_name

                    if mentor_readiness_filter.value != TABLEAU_ALL:
                        filters["Readiness Area"] = mentor_readiness_filter.value

                    mentor_tableau.set_content(
                        tableau_iframe(
                            tableau_view_url(
                                TABLEAU_MENTOR_URL,
                                filters,
                            ),
                            height=1200,
                        )
                    )

                mentor_student_filter.on(
                    "update:model-value",
                    lambda _: update_mentor_tableau(),
                )

                mentor_readiness_filter.on(
                    "update:model-value",
                    lambda _: update_mentor_tableau(),
                )


            priority_panel.set_visibility(False)
            sessions_panel.set_visibility(False)
            evaluations_panel.set_visibility(False)
            analytics_panel.set_visibility(False)
    finally:
        db.close()


@ui.page("/faculty")
def faculty_page():
    user = require_role(UserRole.FACULTY)

    if not user:
        return

    navigation(user)

    db = db_session()

    try:
        students = db.scalars(
            select(User)
            .where(User.role == UserRole.STUDENT, User.is_active.is_(True))
            .order_by(User.full_name)
        ).all()

        mentors = db.scalars(
            select(User)
            .where(User.role == UserRole.MENTOR, User.is_active.is_(True))
            .order_by(User.full_name)
        ).all()

        def show_faculty_section(name):
            sections = {
                "overview": overview_panel,
                "priorities": priorities_panel,
                "assignments": assignments_panel,
                "roles": roles_panel,
                "analytics": analytics_panel,
            }
            for section_name, panel in sections.items():
                panel.set_visibility(section_name == name)

        with ui.left_drawer(value=True).props("bordered width=260 breakpoint=700").classes("bg-white px-2 pt-2 pb-3 shadow-sm") as faculty_drawer:
            with ui.row().classes("w-full justify-start items-center mb-2"):
                ui.button(icon="menu", on_click=faculty_drawer.toggle).props("round dense flat color=primary").tooltip("Collapse navigation")
            ui.button("Cohort Overview", icon="groups", on_click=lambda: show_faculty_section("overview")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Mentor Prioritization", icon="priority_high", on_click=lambda: show_faculty_section("priorities")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Mentor Assignments", icon="assignment_ind", on_click=lambda: show_faculty_section("assignments")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Role Research Profiles", icon="business_center", on_click=lambda: show_faculty_section("roles")).props("flat no-caps align=left").classes("w-full justify-start text-left")
            ui.button("Placement Analytics", icon="analytics", on_click=lambda: show_faculty_section("analytics")).props("flat no-caps align=left").classes("w-full justify-start text-left")

        with ui.page_sticky(position="top-left", x_offset=8, y_offset=8):
            faculty_open_button = ui.button(icon="menu", on_click=faculty_drawer.toggle).props("round dense unelevated color=primary").tooltip("Open navigation")
            faculty_open_button.bind_visibility_from(faculty_drawer, "value", backward=lambda value: not value)

        with ui.column().classes("w-full px-6 py-5 gap-5"):
            heading(
                "Faculty dashboard",
                "Cohort-level readiness and mentor allocation.",
            )

            with ui.column().classes("w-full gap-4") as overview_panel:
                section_heading("Cohort Overview", "Summary of active students, mentors, offers, and cohort readiness by dimension.")
                with ui.row().classes("w-full gap-4"):
                    with ui.card():
                        ui.label("Students")
                        ui.label(str(len(students))).classes("text-3xl font-bold")

                    with ui.card():
                        ui.label("Mentors")
                        ui.label(str(len(mentors))).classes("text-3xl font-bold")

                    offer_count = db.scalar(
                        select(func.count(PlacementOutcome.id)).where(
                            PlacementOutcome.stage == PlacementStage.OFFER,
                            PlacementOutcome.result == PlacementResult.PASSED,
                        )
                    ) or 0

                    with ui.card():
                        ui.label("Recorded offers")
                        ui.label(str(offer_count)).classes("text-3xl font-bold")

                ui.separator()

                ui.label("Cohort readiness by dimension").classes("text-2xl font-semibold")

                dimension_values = {
                    dimension.value: []
                    for dimension in ReadinessDimension
                }

                priority_rows = []

                for student in students:
                    readiness = get_student_readiness(db, student.id)
                    priority = calculate_mentor_priority(db, student.id)

                    for dimension, score in readiness["dimension_scores"].items():
                        if score is not None:
                            dimension_values[dimension].append(score)

                    priority_rows.append(
                        {
                            "id": student.id,
                            "student": student.full_name,
                            "readiness": (
                                f"{readiness['overall_score']:.1f}%"
                                if readiness["overall_score"] is not None
                                else "Unknown"
                            ),
                            "confidence": readiness["confidence"].title(),
                            "bottleneck": (
                                readiness["bottleneck"].replace("_", " ").title()
                                if readiness["bottleneck"]
                                else "Unknown"
                            ),
                            "mentor_priority": priority["priority_score"],
                        }
                    )

                cohort_rows = []

                for dimension in ReadinessDimension:
                    values = dimension_values[dimension.value]

                    cohort_rows.append(
                        {
                            "dimension": dimension.value.replace("_", " ").title(),
                            "average": round(sum(values) / len(values), 1) if values else "No data",
                            "students": len(values),
                        }
                    )

                ui.table(
                    columns=[
                        {
                            "name": "dimension",
                            "label": "Dimension",
                            "field": "dimension",
                        },
                        {
                            "name": "average",
                            "label": "Average",
                            "field": "average",
                        },
                        {
                            "name": "students",
                            "label": "Evidence count",
                            "field": "students",
                        },
                    ],
                    rows=cohort_rows,
                    row_key="dimension",
                )

            with ui.column().classes("w-full gap-4") as priorities_panel:
                section_heading("Mentor Prioritization", "Rank students by who should receive limited mentor time first.")
                ui.separator()

                ui.label("Mentor prioritization").classes("text-2xl font-semibold")

                priority_rows.sort(
                    key=lambda item: item["mentor_priority"],
                    reverse=True,
                )

                ui.table(
                    columns=[
                        {
                            "name": "student",
                            "label": "Student",
                            "field": "student",
                        },
                        {
                            "name": "readiness",
                            "label": "Readiness",
                            "field": "readiness",
                        },
                        {
                            "name": "confidence",
                            "label": "Confidence",
                            "field": "confidence",
                        },
                        {
                            "name": "bottleneck",
                            "label": "Bottleneck",
                            "field": "bottleneck",
                        },
                        {
                            "name": "mentor_priority",
                            "label": "Mentor priority",
                            "field": "mentor_priority",
                        },
                    ],
                    rows=priority_rows,
                    row_key="id",
                )

            with ui.column().classes("w-full gap-4") as assignments_panel:
                section_heading("Mentor Assignments", "Review current student-to-mentor assignments and reassign students when needed.")
                active_assignment_records = db.scalars(
                    select(MentorStudentAssignment).where(
                        MentorStudentAssignment.active.is_(True)
                    )
                ).all()

                mentor_by_id = {
                    mentor.id: mentor
                    for mentor in mentors
                }

                assignment_by_student_id = {
                    assignment.student_id: assignment
                    for assignment in active_assignment_records
                }

                active_assignment_rows = []

                for student in students:
                    assignment = assignment_by_student_id.get(student.id)

                    assigned_mentor = (
                        mentor_by_id.get(assignment.mentor_id)
                        if assignment
                        else None
                    )

                    active_assignment_rows.append(
                        {
                            "student": student.full_name,
                            "mentor": (
                                assigned_mentor.full_name
                                if assigned_mentor
                                else "Unassigned"
                            ),
                        }
                    )

                ui.separator()

                ui.label("Current mentor assignments").classes("text-2xl font-semibold")

                ui.table(
                    columns=[
                        {
                            "name": "student",
                            "label": "Student",
                            "field": "student",
                        },
                        {
                            "name": "mentor",
                            "label": "Assigned mentor",
                            "field": "mentor",
                        },
                    ],
                    rows=active_assignment_rows,
                    row_key="student",
                ).classes("w-full")

                if students and mentors:
                    ui.separator()

                    ui.label("Assign or reassign mentor").classes("text-2xl font-semibold")

                    ui.label("Student to assign").classes("font-medium text-slate-700")
                    student_select = ui.select(
                        {student.id: student.full_name for student in students},
                        label="Select student",
                    ).props("outlined options-dense").classes("w-full max-w-xl")

                    ui.label("Mentor to assign").classes("font-medium text-slate-700 mt-2")
                    mentor_select = ui.select(
                        {mentor.id: mentor.full_name for mentor in mentors},
                        label="Select mentor",
                    ).props("outlined options-dense").classes("w-full max-w-xl")

                    def assign_mentor():
                        if not student_select.value or not mentor_select.value:
                            ui.notify("Select student and mentor.", type="warning")
                            return

                        local_db = db_session()

                        try:
                            selected_student_id = int(student_select.value)
                            selected_mentor_id = int(mentor_select.value)

                            student = local_db.get(User, selected_student_id)
                            mentor = local_db.get(User, selected_mentor_id)

                            if not student or student.role != UserRole.STUDENT:
                                ui.notify("Invalid student.", type="negative")
                                return

                            if not mentor or mentor.role != UserRole.MENTOR:
                                ui.notify("Invalid mentor.", type="negative")
                                return

                            current_assignments = local_db.scalars(
                                select(MentorStudentAssignment).where(
                                    MentorStudentAssignment.student_id == selected_student_id,
                                    MentorStudentAssignment.active.is_(True),
                                )
                            ).all()

                            for assignment in current_assignments:
                                assignment.active = False

                            existing = local_db.scalar(
                                select(MentorStudentAssignment).where(
                                    MentorStudentAssignment.student_id == selected_student_id,
                                    MentorStudentAssignment.mentor_id == selected_mentor_id,
                                )
                            )

                            if existing:
                                existing.active = True
                                existing.assigned_by_id = user.id

                            else:
                                local_db.add(
                                    MentorStudentAssignment(
                                        student_id=selected_student_id,
                                        mentor_id=selected_mentor_id,
                                        assigned_by_id=user.id,
                                        active=True,
                                    )
                                )

                            local_db.commit()

                            ui.notify(
                                f"{student.full_name} assigned to {mentor.full_name}.",
                                type="positive",
                            )

                            ui.navigate.to("/faculty")

                        except Exception as exc:
                            local_db.rollback()
                            ui.notify(f"Could not assign mentor: {exc}", type="negative")

                        finally:
                            local_db.close()

                    ui.button("Assign", on_click=assign_mentor)

            with ui.column().classes("w-full gap-4") as roles_panel:
                section_heading("Role Research Profiles", "Review company and role profiles researched by the system.")
                ui.separator()

                ui.label("Researched company / role profiles").classes(
                    "text-2xl font-semibold"
                )

                role_profiles = db.scalars(
                    select(RoleProfile).order_by(RoleProfile.updated_at.desc())
                ).all()

                role_rows = [
                    {
                        "id": item.id,
                        "company": item.company_name,
                        "role": item.role_name,
                        "updated": item.updated_at.strftime("%Y-%m-%d"),
                    }
                    for item in role_profiles
                ]

                ui.table(
                    columns=[
                        {
                            "name": "company",
                            "label": "Company",
                            "field": "company",
                        },
                        {
                            "name": "role",
                            "label": "Role",
                            "field": "role",
                        },
                        {
                            "name": "updated",
                            "label": "Updated",
                            "field": "updated",
                        },
                    ],
                    rows=role_rows,
                    row_key="id",
                )

            with ui.column().classes("w-full gap-4") as analytics_panel:
                section_heading(
                    "Placement Readiness Analytics",
                    "Explore cohort readiness, assessment effectiveness, and recruitment outcomes.",
                )
                ui.separator()

                faculty_students_by_id = {
                    str(student.id): student
                    for student in students
                }

                faculty_mentors_by_id = {
                    str(mentor.id): mentor
                    for mentor in mentors
                }

                faculty_assignment_records = db.scalars(
                    select(MentorStudentAssignment).where(
                        MentorStudentAssignment.active.is_(True)
                    )
                ).all()

                faculty_students_by_mentor = {}

                for assignment in faculty_assignment_records:
                    faculty_students_by_mentor.setdefault(
                        str(assignment.mentor_id),
                        set(),
                    ).add(
                        str(assignment.student_id)
                    )

                faculty_all_student_options = {
                    TABLEAU_ALL: "All students",
                    **{
                        str(student.id): student.full_name
                        for student in students
                    },
                }

                faculty_mentor_options = {
                    TABLEAU_ALL: "All mentors",
                    **{
                        str(mentor.id): mentor.full_name
                        for mentor in mentors
                    },
                }

                with ui.row().classes("w-full items-end gap-4 flex-wrap"):
                    faculty_student_filter = ui.select(
                        faculty_all_student_options,
                        value=TABLEAU_ALL,
                        label="Student",
                    ).props(
                        "outlined options-dense"
                    ).classes(
                        "w-full max-w-sm"
                    )

                    faculty_mentor_filter = ui.select(
                        faculty_mentor_options,
                        value=TABLEAU_ALL,
                        label="Mentor",
                    ).props(
                        "outlined options-dense"
                    ).classes(
                        "w-full max-w-sm"
                    )

                    faculty_readiness_filter = ui.select(
                        TABLEAU_READINESS_AREAS,
                        value=TABLEAU_ALL,
                        label="Readiness area",
                    ).props(
                        "outlined options-dense"
                    ).classes(
                        "w-full max-w-sm"
                    )

                ui.add_head_html(
                    '<script type="module" '
                    'src="https://public.tableau.com/javascripts/api/'
                    'tableau.embedding.3.latest.min.js"></script>'
                )

                faculty_tableau = ui.html(
                    tableau_viz_element(
                        TABLEAU_FACULTY_URL,
                        "faculty-tableau-viz",
                        height=1200,
                    ),
                    sanitize=False,
                ).classes("w-full")

                def update_faculty_tableau():
                    selected_student = faculty_students_by_id.get(
                        str(faculty_student_filter.value)
                    )

                    selected_mentor = faculty_mentors_by_id.get(
                        str(faculty_mentor_filter.value)
                    )

                    readiness_area = faculty_readiness_filter.value
                    assessment_types = TABLEAU_ASSESSMENTS_BY_READINESS_AREA.get(
                        readiness_area
                    )

                    student_name = (
                        selected_student.full_name
                        if selected_student
                        else None
                    )
                    mentor_name = (
                        selected_mentor.full_name
                        if selected_mentor
                        else None
                    )

                    js_student_name = json.dumps(student_name)
                    js_mentor_name = json.dumps(mentor_name)
                    js_readiness_area = json.dumps(
                        None
                        if readiness_area == TABLEAU_ALL
                        else readiness_area
                    )
                    js_assessment_types = json.dumps(assessment_types)

                    ui.run_javascript(
                        f"""
                        (async () => {{
                            const viz = document.getElementById('faculty-tableau-viz');
                            if (!viz || !viz.workbook || !viz.workbook.activeSheet) {{
                                return;
                            }}

                            const dashboard = viz.workbook.activeSheet;
                            const worksheets = dashboard.worksheets || [];
                            const studentName = {js_student_name};
                            const mentorName = {js_mentor_name};
                            const readinessArea = {js_readiness_area};
                            const assessmentTypes = {js_assessment_types};

                            const applyOrClearEverywhere = async (fieldName, value) => {{
                                await Promise.all(worksheets.map(async worksheet => {{
                                    try {{
                                        if (value) {{
                                            await worksheet.applyFilterAsync(
                                                fieldName,
                                                [value],
                                                'replace'
                                            );
                                        }} else {{
                                            await worksheet.clearFilterAsync(fieldName);
                                        }}
                                    }} catch (error) {{
                                        // A worksheet may not contain this field.
                                    }}
                                }}));
                            }};

                            await applyOrClearEverywhere('Student Name', studentName);
                            await applyOrClearEverywhere('Mentor Name', mentorName);

                            const readinessSheets = [
                                'Cohort Strengths and Weaknesses',
                                'Cohort Improvement across Readiness Areas'
                            ];

                            await Promise.all(readinessSheets.map(async sheetName => {{
                                const worksheet = worksheets.find(
                                    item => item.name === sheetName
                                );
                                if (!worksheet) return;

                                try {{
                                    if (readinessArea) {{
                                        await worksheet.applyFilterAsync(
                                            'Readiness Area',
                                            [readinessArea],
                                            'replace'
                                        );
                                    }} else {{
                                        await worksheet.clearFilterAsync('Readiness Area');
                                    }}
                                }} catch (error) {{
                                    console.warn(
                                        `Could not filter ${{sheetName}} by readiness area`,
                                        error
                                    );
                                }}
                            }}));

                            const assessmentWorksheet = worksheets.find(
                                item => item.name === 'Assessment Effectiveness'
                            );

                            if (assessmentWorksheet) {{
                                try {{
                                    if (assessmentTypes && assessmentTypes.length < 3) {{
                                        await assessmentWorksheet.applyFilterAsync(
                                            'Activity Type',
                                            assessmentTypes,
                                            'replace'
                                        );
                                    }} else {{
                                        await assessmentWorksheet.clearFilterAsync(
                                            'Activity Type'
                                        );
                                    }}
                                }} catch (error) {{
                                    console.warn(
                                        'Could not map readiness area to assessments',
                                        error
                                    );
                                }}
                            }}
                        }})();
                        """
                    )

                def update_faculty_student_options():
                    selected_mentor_id = str(
                        faculty_mentor_filter.value
                    )

                    if selected_mentor_id == TABLEAU_ALL:
                        options = faculty_all_student_options
                    else:
                        allowed_ids = faculty_students_by_mentor.get(
                            selected_mentor_id,
                            set(),
                        )

                        options = {
                            TABLEAU_ALL: "All students",
                            **{
                                student_id: faculty_students_by_id[student_id].full_name
                                for student_id in allowed_ids
                                if student_id in faculty_students_by_id
                            },
                        }

                    faculty_student_filter.options = options

                    if faculty_student_filter.value not in options:
                        faculty_student_filter.value = TABLEAU_ALL

                    faculty_student_filter.update()
                    update_faculty_tableau()

                faculty_student_filter.on(
                    "update:model-value",
                    lambda _: update_faculty_tableau(),
                )

                faculty_mentor_filter.on(
                    "update:model-value",
                    lambda _: update_faculty_student_options(),
                )

                faculty_readiness_filter.on(
                    "update:model-value",
                    lambda _: update_faculty_tableau(),
                )



            priorities_panel.set_visibility(False)
            assignments_panel.set_visibility(False)
            roles_panel.set_visibility(False)
            analytics_panel.set_visibility(False)
    finally:
        db.close()


ui.run(
    title=settings.app_name,
    host=settings.host,
    port=settings.port,
    storage_secret=(
        settings.app_storage_secret
    ),
    reload=False,
    reconnect_timeout=60,
)
