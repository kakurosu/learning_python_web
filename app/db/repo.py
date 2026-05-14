"""Repository layer: thin wrappers around SQLAlchemy queries.

The Repository owns the engine + Session factory. The UI layer never imports
SQLAlchemy directly — it only goes through ``Repository`` methods.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Base,
    CellSubmission,
    ChapterProgress,
    ChapterStatus,
    TestResult,
    User,
)


class Repository:
    def __init__(self, db_path: Path):
        db_path = db_path.resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", future=True)
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    # ------------------------------------------------------------------
    def session(self) -> Session:
        return self._Session()

    # ------------------------------------------------------------------
    # Users
    def get_or_create_default_user(self) -> User:
        with self.session() as s:
            user = s.scalar(select(User).where(User.name == "default"))
            if user is None:
                user = User(name="default")
                s.add(user)
                s.commit()
                s.refresh(user)
            return user

    # ------------------------------------------------------------------
    # Progress
    def get_progress(self, user_id: int, chapter_id: int) -> ChapterProgress | None:
        with self.session() as s:
            return s.scalar(
                select(ChapterProgress).where(
                    ChapterProgress.user_id == user_id,
                    ChapterProgress.chapter_id == chapter_id,
                )
            )

    def upsert_progress(
        self,
        user_id: int,
        chapter_id: int,
        *,
        last_page_index: int,
        status: ChapterStatus,
    ) -> None:
        with self.session() as s:
            row = s.scalar(
                select(ChapterProgress).where(
                    ChapterProgress.user_id == user_id,
                    ChapterProgress.chapter_id == chapter_id,
                )
            )
            if row is None:
                row = ChapterProgress(
                    user_id=user_id,
                    chapter_id=chapter_id,
                    status=status,
                    last_page_index=last_page_index,
                )
                s.add(row)
            else:
                row.status = status
                row.last_page_index = last_page_index
                row.updated_at = datetime.now(UTC).replace(tzinfo=None)
            s.commit()

    def latest_in_progress(self, user_id: int) -> ChapterProgress | None:
        """Return the most recently-touched chapter that is not yet completed."""
        with self.session() as s:
            return s.scalar(
                select(ChapterProgress)
                .where(
                    ChapterProgress.user_id == user_id,
                    ChapterProgress.status != ChapterStatus.completed,
                )
                .order_by(ChapterProgress.updated_at.desc())
            )

    def all_progress(self, user_id: int) -> list[ChapterProgress]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(ChapterProgress).where(ChapterProgress.user_id == user_id)
                ).all()
            )

    def reset_all(self, user_id: int) -> None:
        with self.session() as s:
            for row in s.scalars(
                select(ChapterProgress).where(ChapterProgress.user_id == user_id)
            ).all():
                s.delete(row)
            s.commit()

    # ------------------------------------------------------------------
    # Submissions
    def record_submission(
        self,
        user_id: int,
        chapter_id: int,
        page_index: int,
        *,
        code: str,
        passed: bool,
        stdout: str,
        stderr: str,
        hint_level_shown: int,
    ) -> None:
        with self.session() as s:
            s.add(
                CellSubmission(
                    user_id=user_id,
                    chapter_id=chapter_id,
                    page_index=page_index,
                    code=code,
                    passed=passed,
                    stdout=stdout,
                    stderr=stderr,
                    hint_level_shown=hint_level_shown,
                )
            )
            s.commit()

    def submissions_for_page(
        self, user_id: int, chapter_id: int, page_index: int
    ) -> list[CellSubmission]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(CellSubmission)
                    .where(
                        CellSubmission.user_id == user_id,
                        CellSubmission.chapter_id == chapter_id,
                        CellSubmission.page_index == page_index,
                    )
                    .order_by(CellSubmission.submitted_at.asc())
                ).all()
            )

    # ------------------------------------------------------------------
    # Test results
    def record_test_result(
        self,
        user_id: int,
        *,
        test_id: str,
        score: int,
        total: int,
        duration_sec: int,
        per_question_json: str,
        started_at: datetime,
        finished_at: datetime,
    ) -> int:
        with self.session() as s:
            row = TestResult(
                user_id=user_id,
                test_id=test_id,
                score=score,
                total=total,
                duration_sec=duration_sec,
                per_question_json=per_question_json,
                started_at=started_at,
                finished_at=finished_at,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def list_test_results(self, user_id: int) -> list[TestResult]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(TestResult)
                    .where(TestResult.user_id == user_id)
                    .order_by(TestResult.finished_at.desc())
                ).all()
            )
