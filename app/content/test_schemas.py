"""Pydantic schemas for the standalone "実力テスト" content.

A test is a YAML file with a list of questions; each question is structurally a
single ExercisePage (so we get fill-in-the-blank + auto-grading for free).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .schemas import ExercisePage


class TestQuestion(ExercisePage):
    """A single test question — same shape as an exercise page."""


class TestSet(BaseModel):
    """A standalone test, e.g. ``phase_a_test.yaml``."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str
    description: str = ""
    phase: Literal["A", "B", "C", "D", "E", "F"]
    time_limit_minutes: int = 30
    pass_score: float = 0.6  # fraction of total
    questions: list[TestQuestion] = Field(min_length=1)


def load_test_set(path: Path) -> TestSet:
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return TestSet.model_validate(raw)


def load_test_sets(directory: Path) -> dict[str, TestSet]:
    """Load every ``content/tests/*.yaml`` file and return them keyed by id."""
    out: dict[str, TestSet] = {}
    if not directory.exists():
        return out
    for p in directory.iterdir():
        if p.suffix.lower() not in (".yaml", ".yml"):
            continue
        ts = load_test_set(p)
        out[ts.id] = ts
    return out
