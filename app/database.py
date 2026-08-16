from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

from sqlalchemy import text


def create_tableau_views() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE OR REPLACE VIEW tableau_readiness_history AS
                SELECT
                    re.id AS evidence_id,
                    re.student_id,
                    u.full_name AS student_name,
                    sp.target_company,
                    sp.target_role,
                    LOWER(re.dimension::text) AS dimension,
                    re.score,
                    LOWER(re.source::text) AS evidence_source,
                    re.verified,
                    re.occurred_at,

                    msa.mentor_id,
                    mentor.full_name AS mentor_name

                FROM readiness_evidence re

                JOIN users u
                    ON u.id = re.student_id

                LEFT JOIN student_profiles sp
                    ON sp.user_id = re.student_id

                LEFT JOIN mentor_student_assignments msa
                    ON msa.student_id = re.student_id
                    AND msa.active = TRUE

                LEFT JOIN users mentor
                    ON mentor.id = msa.mentor_id
                """
            )
        )

        connection.execute(
            text(
                """
                CREATE OR REPLACE VIEW tableau_interventions AS
                SELECT
                    i.id AS intervention_id,
                    i.student_id,
                    student.full_name AS student_name,

                    LOWER(i.dimension::text) AS dimension,
                    LOWER(i.delivery::text) AS delivery,
                    LOWER(i.status::text) AS status,

                    i.title,
                    i.created_at,

                    msa.mentor_id,
                    mentor.full_name AS mentor_name

                FROM interventions i

                JOIN users student
                    ON student.id = i.student_id

                LEFT JOIN mentor_student_assignments msa
                    ON msa.student_id = i.student_id
                    AND msa.active = TRUE

                LEFT JOIN users mentor
                    ON mentor.id = msa.mentor_id
                """
            )
        )

        connection.execute(
            text(
                """
                CREATE OR REPLACE VIEW tableau_mentor_sessions AS
                SELECT
                    ms.id AS session_id,
                    ms.student_id,
                    student.full_name AS student_name,

                    ms.mentor_id,
                    mentor.full_name AS mentor_name,

                    ms.scheduled_for,
                    ms.completed,
                    ms.notes

                FROM mentor_sessions ms

                JOIN users student
                    ON student.id = ms.student_id

                JOIN users mentor
                    ON mentor.id = ms.mentor_id
                """
            )
        )

        connection.execute(
            text(
                """
                CREATE OR REPLACE VIEW tableau_placement_outcomes AS
                SELECT
                    po.id AS outcome_id,
                    po.student_id,
                    student.full_name AS student_name,

                    sp.target_company,
                    sp.target_role,

                    po.company_name,
                    po.role_name,

                    LOWER(po.stage::text) AS stage,
                    LOWER(po.result::text) AS result,

                    po.occurred_at

                FROM placement_outcomes po

                JOIN users student
                    ON student.id = po.student_id

                LEFT JOIN student_profiles sp
                    ON sp.user_id = po.student_id
                """
            )
        )