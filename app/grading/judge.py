"""Grading logic for fill-in-the-blank exercises.

Two-stage evaluation:
1. Form check — each blank's input must match at least one of the blank's
   ``accept_patterns`` regexes (or equal ``canonical_answer``). This catches
   "you didn't use lambda" / "you wrote it without using .mean()" style errors
   without running any code.
2. Behaviour check — the assembled student code is run in the kernel and the
   chapter's ``test_cases`` are evaluated against the resulting state / stdout.

If form check fails but behaviour check passes, we still consider the answer
correct (the student found a valid alternate solution). The reverse — form OK
but behaviour wrong — fails, with the kernel error returned to the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..content.loader import assemble_code
from ..content.schemas import (
    Blank,
    ExercisePage,
    NamespaceCheck,
    PytestLike,
    ReadingPage,
    StdoutRegex,
    TestCase,
)
from ..kernel.manager import ExecutionResult, KernelSession


@dataclass
class BlankFormResult:
    blank_id: str
    passed: bool
    matched_pattern: str | None = None  # which regex matched (None if canonical / fail)


@dataclass
class TestCaseResult:
    kind: str
    passed: bool
    detail: str = ""


@dataclass
class GradingResult:
    overall_passed: bool
    form_results: list[BlankFormResult] = field(default_factory=list)
    test_results: list[TestCaseResult] = field(default_factory=list)
    assembled_code: str = ""
    execution: ExecutionResult | None = None
    failed_blanks: list[str] = field(default_factory=list)

    @property
    def form_passed(self) -> bool:
        return all(r.passed for r in self.form_results)

    @property
    def behaviour_passed(self) -> bool:
        return bool(self.test_results) and all(r.passed for r in self.test_results)


# ---------------------------------------------------------------------------
# Form check
# ---------------------------------------------------------------------------


def check_blank(blank: Blank, value: str) -> BlankFormResult:
    if value.strip() == blank.canonical_answer.strip():
        return BlankFormResult(blank.id, True, matched_pattern="(canonical)")
    for pat in blank.accept_patterns:
        if re.fullmatch(pat, value.strip()):
            return BlankFormResult(blank.id, True, matched_pattern=pat)
    return BlankFormResult(blank.id, False)


def check_blanks(blanks: list[Blank], values: dict[str, str]) -> list[BlankFormResult]:
    return [check_blank(b, values.get(b.id, "")) for b in blanks]


# ---------------------------------------------------------------------------
# Behaviour check
# ---------------------------------------------------------------------------


def _eval_namespace_check(kernel: KernelSession, tc: NamespaceCheck) -> TestCaseResult:
    for expr in tc.asserts:
        passed, info = kernel.evaluate_expression(expr, timeout=5.0)
        if not passed:
            return TestCaseResult("namespace_check", False, f"{expr!r} -> {info}")
    return TestCaseResult("namespace_check", True, "all asserts ok")


def _eval_stdout_regex(stdout: str, tc: StdoutRegex) -> TestCaseResult:
    flags = 0
    for f in tc.flags:
        flags |= getattr(re, f)
    if re.search(tc.pattern, stdout, flags):
        return TestCaseResult("stdout_regex", True, "matched")
    return TestCaseResult("stdout_regex", False, f"pattern not found: {tc.pattern!r}")


def _eval_pytest_like(_assembled: str, _tc: PytestLike) -> TestCaseResult:
    # Phase 1 stub — pytest_like is reserved for advanced chapters / standalone tests.
    return TestCaseResult("pytest_like", False, "pytest_like not yet implemented")


def evaluate_test_cases(
    kernel: KernelSession,
    test_cases: list[TestCase],
    *,
    assembled_code: str,
    stdout: str,
) -> list[TestCaseResult]:
    results: list[TestCaseResult] = []
    for tc in test_cases:
        if isinstance(tc, NamespaceCheck):
            results.append(_eval_namespace_check(kernel, tc))
        elif isinstance(tc, StdoutRegex):
            results.append(_eval_stdout_regex(stdout, tc))
        elif isinstance(tc, PytestLike):
            results.append(_eval_pytest_like(assembled_code, tc))
        else:  # defensive
            results.append(TestCaseResult(type(tc).__name__, False, "unknown test case kind"))
    return results


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def grade_exercise(
    page: ExercisePage,
    blank_values: dict[str, str],
    kernel: KernelSession,
) -> GradingResult:
    """Run form + behaviour checks for a single exercise submission."""

    form_results = check_blanks(page.blanks, blank_values)

    # Always assemble + run the code, even if the form check failed: that lets
    # us award credit when the student found a valid alternate solution that
    # accept_patterns didn't anticipate.
    assembled = assemble_code(
        page.code_template, {b.id: blank_values.get(b.id, "") for b in page.blanks}
    )
    execution = kernel.execute(assembled, timeout=page.timeout_seconds)
    test_results = (
        evaluate_test_cases(
            kernel, page.test_cases, assembled_code=assembled, stdout=execution.stdout
        )
        if execution.status == "ok"
        else []
    )

    behaviour_passed = bool(test_results) and all(r.passed for r in test_results)
    form_passed = all(r.passed for r in form_results)

    # Overall pass: behaviour must pass AND (form must pass OR there were no blanks).
    # If form check fails, we still pass when behaviour is correct — surfaced as
    # "correct alternative solution".
    if execution.status != "ok":
        overall = False
    else:
        overall = behaviour_passed and (form_passed or not page.blanks)
        # Generous: if behaviour passes but form does not, still treat as correct.
        if behaviour_passed and not form_passed:
            overall = True

    return GradingResult(
        overall_passed=overall,
        form_results=form_results,
        test_results=test_results,
        assembled_code=assembled,
        execution=execution,
        failed_blanks=[r.blank_id for r in form_results if not r.passed],
    )


# ---------------------------------------------------------------------------
# Reading (multiple-choice) grading
# ---------------------------------------------------------------------------


def grade_reading(page: ReadingPage, selected_index: int | None) -> GradingResult:
    """Multiple-choice grading. Kernel-free.

    Returns a ``GradingResult`` whose shape matches the exercise pipeline so
    the result overlay (``ResultPageWidget``) can be reused unchanged.
    """
    if selected_index is None or selected_index < 0:
        # Treated as a failed submission rather than an error so the result
        # overlay can show a coherent "Incorrect" with guidance.
        return GradingResult(
            overall_passed=False,
            form_results=[],
            test_results=[
                TestCaseResult(
                    kind="reading",
                    passed=False,
                    detail="選択肢が選ばれていません。",
                )
            ],
            assembled_code=page.code,
            execution=None,
            failed_blanks=[],
        )

    passed = selected_index == page.correct_index
    if passed:
        detail = page.explanation or "正解。次の問題に進もう。"
    else:
        picked = page.choices[selected_index]
        answer = page.choices[page.correct_index]
        explanation = f" — {page.explanation}" if page.explanation else ""
        detail = f"選択した: {picked!s}（正解: {answer!s}）{explanation}"

    return GradingResult(
        overall_passed=passed,
        form_results=[],
        test_results=[TestCaseResult(kind="reading", passed=passed, detail=detail)],
        assembled_code=page.code,
        execution=None,
        failed_blanks=[],
    )
