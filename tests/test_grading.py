"""Tests for the grading judge.

The form-check tests run without spinning up a kernel. Behaviour-check tests
do start a real Jupyter kernel — those are marked with ``kernel`` and can be
deselected with ``pytest -m 'not kernel'`` for fast loops.
"""

from __future__ import annotations

import pytest

from app.content.schemas import (
    Blank,
    ExercisePage,
    NamespaceCheck,
    ReadingPage,
    StdoutRegex,
)
from app.grading.judge import check_blank, check_blanks, grade_exercise, grade_reading


def _blank(id_: str, canonical: str, patterns: list[str]) -> Blank:
    return Blank(
        id=id_,
        placeholder="",
        width=12,
        accept_patterns=patterns,
        canonical_answer=canonical,
        hint="",
    )


# ---------------------------------------------------------------------------
# Form check (pure, no kernel)
# ---------------------------------------------------------------------------


def test_check_blank_canonical_match() -> None:
    b = _blank("s1", "returns.mean()", [])
    res = check_blank(b, "returns.mean()")
    assert res.passed
    assert res.matched_pattern == "(canonical)"


def test_check_blank_pattern_match() -> None:
    b = _blank("s1", "returns.mean()", [r"^np\.mean\(returns\)$"])
    res = check_blank(b, "np.mean(returns)")
    assert res.passed
    assert res.matched_pattern == r"^np\.mean\(returns\)$"


def test_check_blank_fail() -> None:
    b = _blank("s1", "returns.mean()", [r"^np\.mean\(returns\)$"])
    res = check_blank(b, "returns.average()")
    assert not res.passed


def test_check_blank_whitespace_tolerated() -> None:
    b = _blank("s1", "x + y", [])
    res = check_blank(b, "  x + y  ")
    assert res.passed


def test_check_blanks_multi() -> None:
    b1 = _blank("a", "x", [r"^[A-Za-z_]\w*$"])
    b2 = _blank("b", "y", [r"^[A-Za-z_]\w*$"])
    results = check_blanks([b1, b2], {"a": "foo", "b": "bar"})
    assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# Behaviour check (requires kernel)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kernel():
    pytest.importorskip("jupyter_client")
    pytest.importorskip("ipykernel")
    from app.kernel.manager import KernelSession

    k = KernelSession()
    try:
        k.start()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"kernel not available: {e}")
    yield k
    k.shutdown()


@pytest.mark.kernel
def test_grade_exercise_correct_path(kernel) -> None:
    page = ExercisePage(
        kind="exercise",
        title="t",
        prompt="p",
        code_template="x = {{slot:val}}\nprint(x)",
        blanks=[_blank("val", "42", [r"^\d+$"])],
        test_cases=[
            StdoutRegex(kind="stdout_regex", pattern=r"^42\s*$"),
            NamespaceCheck(kind="namespace_check", asserts=["x == 42"]),
        ],
    )
    res = grade_exercise(page, {"val": "42"}, kernel)
    assert res.overall_passed, res.execution.stderr if res.execution else "?"


@pytest.mark.kernel
def test_grade_exercise_wrong_path(kernel) -> None:
    page = ExercisePage(
        kind="exercise",
        title="t",
        prompt="p",
        code_template="x = {{slot:val}}\nprint(x)",
        blanks=[_blank("val", "42", [r"^\d+$"])],
        test_cases=[StdoutRegex(kind="stdout_regex", pattern=r"^42\s*$")],
    )
    res = grade_exercise(page, {"val": "0"}, kernel)
    assert not res.overall_passed


# ---------------------------------------------------------------------------
# Reading grading (kernel-free)
# ---------------------------------------------------------------------------


def _reading_page() -> ReadingPage:
    return ReadingPage(
        kind="reading",
        title="t",
        prompt="p",
        code="print('hi')",
        choices=["a", "b", "c"],
        correct_index=1,
        explanation="b is correct",
    )


def test_grade_reading_correct() -> None:
    page = _reading_page()
    res = grade_reading(page, 1)
    assert res.overall_passed
    assert res.assembled_code == page.code
    assert res.test_results[0].passed
    assert "b is correct" in res.test_results[0].detail


def test_grade_reading_wrong() -> None:
    page = _reading_page()
    res = grade_reading(page, 0)
    assert not res.overall_passed
    assert not res.test_results[0].passed
    detail = res.test_results[0].detail
    assert "a" in detail and "b" in detail


def test_grade_reading_unanswered() -> None:
    page = _reading_page()
    res = grade_reading(page, None)
    assert not res.overall_passed
    assert "選択肢" in res.test_results[0].detail


@pytest.mark.kernel
def test_grade_exercise_alt_solution_when_form_fails(kernel) -> None:
    """When form-check fails but behaviour passes, we still mark as correct."""
    page = ExercisePage(
        kind="exercise",
        title="t",
        prompt="p",
        code_template="x = {{slot:val}}\nprint(x)",
        # accept_patterns only allows "42" but behaviour test only checks output is 42
        blanks=[_blank("val", "42", [r"^42$"])],
        test_cases=[StdoutRegex(kind="stdout_regex", pattern=r"^42\s*$")],
    )
    # Student writes "21*2" — form fails, behaviour passes.
    res = grade_exercise(page, {"val": "21*2"}, kernel)
    assert not res.form_passed
    assert res.behaviour_passed
    assert res.overall_passed
