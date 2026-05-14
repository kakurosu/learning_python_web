"""Tests for content loader + chapter YAML validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.content.loader import ContentError, assemble_code, load_chapter, load_chapters
from app.content.schemas import ExercisePage, ReadingPage, SamplePage

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAPTERS_DIR = REPO_ROOT / "content" / "chapters"


def test_load_chapter_01() -> None:
    ch = load_chapter(CHAPTERS_DIR / "01_hello.yaml")
    assert ch.id == 1
    assert ch.title.startswith("はじめての")
    assert ch.phase == "A"
    assert len(ch.pages) >= 1
    # First page should be sample
    assert isinstance(ch.pages[0], SamplePage)
    # At least one exercise with blanks
    exercises = [p for p in ch.pages if isinstance(p, ExercisePage)]
    assert exercises, "chapter 01 should contain at least one exercise"
    assert any(ex.blanks for ex in exercises)


def test_load_chapters_directory() -> None:
    chapters = load_chapters(CHAPTERS_DIR)
    assert len(chapters) >= 1
    assert chapters[0].id == 1


def test_assemble_code_basic() -> None:
    template = "x = {{slot:val}}\nprint(x)"
    out = assemble_code(template, {"val": "42"})
    assert out == "x = 42\nprint(x)"


def test_assemble_code_missing_slot_raises() -> None:
    with pytest.raises(KeyError):
        assemble_code("x = {{slot:missing}}", {})


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "01_bad.yaml"
    p.write_text("id: 1\n: invalid", encoding="utf-8")
    with pytest.raises(ContentError):
        load_chapter(p)


def test_chapter_id_mismatch_raises(tmp_path: Path) -> None:
    yaml_text = (
        "id: 5\ntitle: x\nphase: A\nlearning_goals: []\nprerequisites: []\n"
        "pages:\n  - kind: sample\n    title: t\n    markdown: m\n"
    )
    (tmp_path / "01_x.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ContentError):
        load_chapters(tmp_path)


# ---------------------------------------------------------------------------
# Reading chapters
# ---------------------------------------------------------------------------


def test_load_reading_phase_a_chapter() -> None:
    # Reading chapter for Phase A — renumbered to slot in after Phase A's
    # last regular chapter (10) instead of starting at 27.
    ch = load_chapter(CHAPTERS_DIR / "11_reading_phase_a.yaml")
    assert ch.id == 11
    assert ch.phase == "A"
    assert ch.pages, "reading chapter should have pages"
    assert all(isinstance(p, ReadingPage) for p in ch.pages)
    first = ch.pages[0]
    assert isinstance(first, ReadingPage)
    assert len(first.choices) >= 2
    assert 0 <= first.correct_index < len(first.choices)


def test_load_all_reading_chapters() -> None:
    """All 6 reading review chapters load and contain only reading pages.

    After the renumber, the reading reviews live at the slot immediately
    after each phase's last regular chapter: 11 (A), 16 (B), 22 (C),
    26 (D), 29 (E), 32 (F).
    """
    for chapter_id in (11, 16, 22, 26, 29, 32):
        matches = list(CHAPTERS_DIR.glob(f"{chapter_id:02d}_reading_*.yaml"))
        assert matches, f"reading chapter {chapter_id} YAML missing"
        ch = load_chapter(matches[0])
        assert ch.id == chapter_id
        assert all(isinstance(p, ReadingPage) for p in ch.pages), (
            f"chapter {chapter_id} should contain only reading pages"
        )


def test_reading_correct_index_out_of_range_raises() -> None:
    """correct_index >= len(choices) must fail validation."""
    with pytest.raises(ValidationError):
        ReadingPage(
            kind="reading",
            title="bad",
            prompt="p",
            code="x = 1",
            choices=["a", "b"],
            correct_index=5,  # out of range
        )
