"""Tests for SQLAlchemy Repository."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.db.models import ChapterStatus
from app.db.repo import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "test.db")


def test_default_user_idempotent(repo: Repository) -> None:
    u1 = repo.get_or_create_default_user()
    u2 = repo.get_or_create_default_user()
    assert u1.id == u2.id


def test_progress_upsert_and_resume(repo: Repository) -> None:
    user = repo.get_or_create_default_user()
    repo.upsert_progress(user.id, 1, last_page_index=2, status=ChapterStatus.in_progress)
    repo.upsert_progress(user.id, 1, last_page_index=4, status=ChapterStatus.in_progress)
    p = repo.get_progress(user.id, 1)
    assert p is not None
    assert p.last_page_index == 4

    latest = repo.latest_in_progress(user.id)
    assert latest is not None
    assert latest.chapter_id == 1


def test_completion_excluded_from_resume(repo: Repository) -> None:
    user = repo.get_or_create_default_user()
    repo.upsert_progress(user.id, 1, last_page_index=5, status=ChapterStatus.completed)
    assert repo.latest_in_progress(user.id) is None


def test_reset_all(repo: Repository) -> None:
    user = repo.get_or_create_default_user()
    repo.upsert_progress(user.id, 1, last_page_index=2, status=ChapterStatus.in_progress)
    repo.upsert_progress(user.id, 2, last_page_index=1, status=ChapterStatus.in_progress)
    repo.reset_all(user.id)
    assert repo.all_progress(user.id) == []


def test_record_submission(repo: Repository) -> None:
    user = repo.get_or_create_default_user()
    repo.record_submission(
        user.id,
        chapter_id=1,
        page_index=2,
        code='print("x")',
        passed=True,
        stdout="x",
        stderr="",
        hint_level_shown=0,
    )
    subs = repo.submissions_for_page(user.id, 1, 2)
    assert len(subs) == 1
    assert subs[0].passed is True


def test_record_test_result(repo: Repository) -> None:
    user = repo.get_or_create_default_user()
    now = datetime.now(UTC).replace(tzinfo=None)
    rid = repo.record_test_result(
        user.id,
        test_id="phase_a_test",
        score=8,
        total=10,
        duration_sec=540,
        per_question_json="[]",
        started_at=now,
        finished_at=now,
    )
    assert rid >= 1
    rows = repo.list_test_results(user.id)
    assert len(rows) == 1
    assert rows[0].score == 8
