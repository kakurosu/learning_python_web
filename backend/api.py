"""FastAPI app — serves the web UI and exposes JSON endpoints.

The frontend (static files under ``frontend/static`` and Jinja templates
under ``frontend/templates``) talks to these endpoints over plain HTTP on
``127.0.0.1``. The whole thing is wrapped in a pywebview window by
``main.py`` so the user sees it as a desktop app.

Endpoints (initial skeleton — more added in later phases):

    GET  /                          Dashboard HTML
    GET  /api/chapters              chapter list (JSON)
    GET  /api/chapters/{id}         chapter detail (JSON)
    POST /api/grade                 grade an exercise submission
    GET  /api/progress              latest progress for the default user
    PUT  /api/progress/{chapter_id} upsert progress for a chapter
    POST /api/llm                   Ask AI
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.content.schemas import Chapter, ExercisePage, ReadingPage, SamplePage
from app.db.models import ChapterStatus
from app.grading.judge import grade_exercise, grade_reading

from .deps import (
    PROJECT_ROOT,
    get_chapters,
    get_kernel,
    get_llm,
    get_repo,
    get_test_sets,
    get_user_id,
)


# Phase metadata (mirrors the PyQt6 version's PHASE_INFO)
PHASE_INFO: list[tuple[str, str, str]] = [
    ("A", "Python 文法基礎",       "変数・演算・分岐・ループ・関数まで"),
    ("B", "数値・データライブラリ",  "NumPy / pandas / matplotlib"),
    ("C", "金融計算 (CMA)",         "期待値・共分散・最適化・MC"),
    ("D", "ML / DL",               "ARIMA / scikit-learn / PyTorch"),
    ("E", "外部連携",               "requests / OpenAI SDK"),
    ("F", "アプリ開発",             "Streamlit / 自動操作"),
]
PHASE_LABEL = {p: f"Phase {p}" for p in "ABCDEF"}


def _phase_stats(chapters: list[Chapter], progress_map: dict) -> dict[str, dict]:
    """{ 'A': {'total': N, 'done': M, 'inprog': K, 'pct': P}, ... }"""
    out: dict[str, dict] = {p: {"total": 0, "done": 0, "inprog": 0}
                            for p in "ABCDEF"}
    for ch in chapters:
        out[ch.phase]["total"] += 1
    for cid, prog in progress_map.items():
        ch = next((c for c in chapters if c.id == cid), None)
        if ch is None:
            continue
        if prog.status == ChapterStatus.completed:
            out[ch.phase]["done"] += 1
        elif prog.status == ChapterStatus.in_progress:
            out[ch.phase]["inprog"] += 1
    for p, d in out.items():
        d["pct"] = (0 if d["total"] == 0 else int(d["done"] / d["total"] * 100))
    return out


def _latest_in_progress(chapters: list[Chapter], repo) -> tuple[Chapter | None, int]:
    prog = repo.latest_in_progress(get_user_id())
    if prog is None:
        return None, 0
    ch = next((c for c in chapters if c.id == prog.chapter_id), None)
    return ch, prog.last_page_index


def _render_md(text: str) -> str:
    """Render markdown to HTML. Used for sample / exercise / reading prompts."""
    if not text:
        return ""
    return md_lib.markdown(text, extensions=["fenced_code", "tables"])


_SLOT_RE = re.compile(r"\{\{slot:([^}\s]+)\}\}")


def _render_template_with_blanks(template: str, blanks_by_id: dict) -> str:
    """Turn the chapter's ``code_template`` into HTML with inline blank inputs.

    Each ``{{slot:id}}`` becomes an ``<input class="blank" data-slot="id">``
    so the user can type into it. Lines are wrapped in numbered rows so the
    output looks like a code editor with a line-number gutter.
    """
    lines = template.splitlines() or [""]
    digits = max(2, len(str(len(lines))))

    def _sub_slot(m: re.Match[str]) -> str:
        sid = m.group(1)
        b = blanks_by_id.get(sid)
        placeholder = (b.placeholder if b else "...")
        # The width hint comes from blank.width (rough char count) — clamp it.
        width_chars = (b.width if b else 12)
        return (
            f'<input class="blank" data-slot="{sid}" '
            f'placeholder="{placeholder}" '
            f'style="min-width: {max(80, width_chars * 9)}px; '
            f'max-width: {max(120, width_chars * 14)}px;" />'
        )

    rendered_lines: list[str] = []
    for i, line in enumerate(lines, start=1):
        body = _SLOT_RE.sub(_sub_slot, _html_escape(line))
        rendered_lines.append(
            f'<span class="ln">{str(i).rjust(digits)}</span>{body}'
        )
    return "\n".join(rendered_lines) or "&nbsp;"


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )

log = logging.getLogger("api")

FRONTEND_DIR = PROJECT_ROOT / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"


# ---------------------------------------------------------------------------
# App + static + templates
# ---------------------------------------------------------------------------

app = FastAPI(title="Study Python for Finance", docs_url="/api/docs")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Pages (server-rendered HTML)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request) -> HTMLResponse:
    chapters = get_chapters()
    repo = get_repo()
    progress_map = {p.chapter_id: p for p in repo.all_progress(get_user_id())}
    latest_ch, latest_page = _latest_in_progress(chapters, repo)

    n_total  = len(chapters)
    n_done   = sum(1 for p in progress_map.values()
                   if p.status == ChapterStatus.completed)
    n_inprog = sum(1 for p in progress_map.values()
                   if p.status == ChapterStatus.in_progress)

    # Tests average score (history)
    results = repo.list_test_results(get_user_id())
    avg = (int(sum(r.score / max(r.total, 1) for r in results)
               / len(results) * 100) if results else None)

    phase_rows = []
    stats = _phase_stats(chapters, progress_map)
    for phase, ttl, _desc in PHASE_INFO:
        s = stats[phase]
        phase_rows.append({
            "phase": phase, "title": ttl,
            "done": s["done"], "total": s["total"], "pct": s["pct"],
        })

    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "active": "dashboard",
            "latest_ch": latest_ch, "latest_page": latest_page,
            "phase_rows": phase_rows,
            "n_total": n_total, "n_done": n_done, "n_inprog": n_inprog,
            "avg_score": avg,
            "phase_label": PHASE_LABEL,
        },
    )


@app.get("/chapters", response_class=HTMLResponse)
def page_chapters(request: Request) -> HTMLResponse:
    chapters = get_chapters()
    repo = get_repo()
    progress_map = {p.chapter_id: p for p in repo.all_progress(get_user_id())}

    n_done = sum(1 for p in progress_map.values()
                 if p.status == ChapterStatus.completed)
    n_inprog = sum(1 for p in progress_map.values()
                   if p.status == ChapterStatus.in_progress)
    n_remain = len(chapters) - n_done

    # group by phase
    groups = []
    for phase, ttl, desc in PHASE_INFO:
        chs = [c for c in chapters if c.phase == phase]
        if not chs:
            continue
        rows = []
        ph_done = ph_inprog = 0
        for c in chs:
            p = progress_map.get(c.id)
            status = p.status.value if p else "not_started"
            pct = (100 if status == "completed"
                   else 50 if status == "in_progress" else 0)
            if status == "completed": ph_done += 1
            elif status == "in_progress": ph_inprog += 1
            rows.append({
                "id": c.id, "title": c.title,
                "goal": c.learning_goals[0] if c.learning_goals else "",
                "status": status, "pct": pct,
            })
        groups.append({
            "phase": phase, "title": ttl, "desc": desc,
            "total": len(chs), "done": ph_done, "inprog": ph_inprog,
            "rows": rows,
        })

    return templates.TemplateResponse(
        request, "chapters.html",
        {
            "active": "chapters",
            "groups": groups,
            "n_done": n_done, "n_inprog": n_inprog, "n_remain": n_remain,
            "phase_label": PHASE_LABEL,
        },
    )


@app.get("/history", response_class=HTMLResponse)
def page_history(request: Request) -> HTMLResponse:
    repo = get_repo()
    results = repo.list_test_results(get_user_id())
    rows = []
    best = None
    for r in results:
        ratio = r.score / max(r.total, 1)
        passed = ratio >= 0.6
        if best is None or ratio > (best.score / max(best.total, 1)):
            best = r
        rows.append({
            "score": r.score, "total": r.total,
            "test_id": r.test_id,
            "finished_at": r.finished_at.strftime("%Y-%m-%d %H:%M"),
            "duration": f"{r.duration_sec // 60}分{r.duration_sec % 60}秒",
            "passed": passed,
        })
    avg = (int(sum(r.score / max(r.total, 1) for r in results)
               / len(results) * 100) if results else 0)
    best_text = (f"{best.score}/{best.total}" if best else "—")
    return templates.TemplateResponse(
        request, "history.html",
        {
            "active": "history",
            "rows": rows, "attempts": len(results),
            "avg": avg, "best": best_text,
        },
    )


@app.get("/practice", response_class=HTMLResponse)
def page_practice(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "placeholder.html",
        {"active": "practice", "title": "練習問題",
         "subtitle": "Phase 横断の総合練習をまとめた画面。"},
    )


@app.get("/references", response_class=HTMLResponse)
def page_refs(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "placeholder.html",
        {"active": "references", "title": "リファレンス",
         "subtitle": "標準ライブラリと主要パッケージの早見表。"},
    )


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "placeholder.html",
        {"active": "settings", "title": "設定",
         "subtitle": "テーマ・ショートカット・API キーなどを変更できます。"},
    )


@app.get("/chapter/{chapter_id}", response_class=HTMLResponse)
def page_chapter(request: Request, chapter_id: int, page: int = 0) -> HTMLResponse:
    chapters = get_chapters()
    ch = next((c for c in chapters if c.id == chapter_id), None)
    if ch is None:
        raise HTTPException(404, f"chapter {chapter_id} not found")
    page_index = max(0, min(page, len(ch.pages) - 1))
    pg = ch.pages[page_index]

    # Persist that the user is now viewing this page.
    get_repo().upsert_progress(
        user_id=get_user_id(),
        chapter_id=chapter_id,
        last_page_index=page_index,
        status=ChapterStatus.in_progress,
    )

    # Page-specific render context
    if isinstance(pg, SamplePage):
        kind = "sample"
        ctx = {
            "markdown_html": _render_md(pg.markdown),
            "sample_code": pg.sample_code,
            "runnable": pg.runnable,
            "runner": pg.runner,
        }
    elif isinstance(pg, ExercisePage):
        kind = "exercise"
        blanks_by_id = {b.id: b for b in pg.blanks}
        ctx = {
            "prompt_html": _render_md(pg.prompt),
            "code_html": _render_template_with_blanks(pg.code_template, blanks_by_id),
            "hints": list(pg.hints) if pg.hints else [],
        }
    elif isinstance(pg, ReadingPage):
        kind = "reading"
        ctx = {
            "prompt_html": _render_md(pg.prompt),
            "code": pg.code,
            "code_file_label": pg.code_file_label,
            "choices": list(pg.choices),
        }
    else:
        raise HTTPException(500, f"unknown page kind: {type(pg).__name__}")

    speech = getattr(pg, "stickman_speech", "")
    mood = getattr(pg, "stickman", "explain")

    return templates.TemplateResponse(
        request, "chapter.html",
        {
            "active": "chapters",
            "chapter": ch,
            "page_index": page_index,
            "page": pg,
            "kind": kind,
            "ctx": ctx,
            "mood": mood,
            "speech": speech,
            "is_last": (page_index + 1 >= len(ch.pages)),
            "phase_label": PHASE_LABEL,
        },
    )


@app.get("/tests", response_class=HTMLResponse)
def page_tests(request: Request) -> HTMLResponse:
    ts_list = list(get_test_sets().values())
    return templates.TemplateResponse(
        request, "tests.html",
        {"active": "tests", "tests": ts_list},
    )


@app.get("/test/{test_id}", response_class=HTMLResponse)
def page_test_runner(request: Request, test_id: str) -> HTMLResponse:
    ts = get_test_sets().get(test_id)
    if ts is None:
        raise HTTPException(404, f"test {test_id} not found")

    # Build all questions as inline blank-renderable HTML
    questions = []
    for i, q in enumerate(ts.questions):
        blanks_by_id = {b.id: b for b in q.blanks}
        questions.append({
            "index": i,
            "title": q.title,
            "prompt_html": _render_md(q.prompt),
            "code_html": _render_template_with_blanks(q.code_template, blanks_by_id),
        })

    return templates.TemplateResponse(
        request, "test_runner.html",
        {
            "active": "tests",
            "test": ts,
            "questions": questions,
        },
    )


# ---------------------------------------------------------------------------
# JSON API — test grading (single question)
# ---------------------------------------------------------------------------


class TestGradeRequest(BaseModel):
    test_id: str
    question_index: int
    values: dict[str, str] = {}


@app.post("/api/test/grade")
def api_test_grade(req: TestGradeRequest) -> dict:
    ts = get_test_sets().get(req.test_id)
    if ts is None:
        raise HTTPException(404, "test not found")
    if not (0 <= req.question_index < len(ts.questions)):
        raise HTTPException(400, "question_index out of range")
    q = ts.questions[req.question_index]
    gr = grade_exercise(q, req.values, get_kernel())
    return {
        "overall_passed": gr.overall_passed,
        "failed_blanks": gr.failed_blanks,
        "stdout": (gr.execution.stdout if gr.execution else ""),
        "stderr": (gr.execution.stderr if gr.execution else ""),
    }


class TestRecordRequest(BaseModel):
    test_id: str
    score: int
    total: int
    duration_sec: int
    per_question_json: str = "[]"


@app.post("/api/test/record")
def api_test_record(req: TestRecordRequest) -> dict:
    from datetime import UTC, datetime
    now = datetime.now(UTC).replace(tzinfo=None)
    get_repo().record_test_result(
        user_id=get_user_id(),
        test_id=req.test_id,
        score=req.score,
        total=req.total,
        duration_sec=req.duration_sec,
        per_question_json=req.per_question_json,
        started_at=now,
        finished_at=now,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# JSON API — chapters
# ---------------------------------------------------------------------------


class ChapterSummary(BaseModel):
    id: int
    phase: str
    title: str
    learning_goals: list[str]
    status: str
    page_count: int
    last_page_index: int


@app.get("/api/chapters", response_model=list[ChapterSummary])
def api_chapters() -> list[ChapterSummary]:
    chapters: list[Chapter] = get_chapters()
    repo = get_repo()
    progress_map = {p.chapter_id: p for p in repo.all_progress(get_user_id())}
    out: list[ChapterSummary] = []
    for ch in chapters:
        p = progress_map.get(ch.id)
        out.append(
            ChapterSummary(
                id=ch.id,
                phase=ch.phase,
                title=ch.title,
                learning_goals=list(ch.learning_goals),
                status=(p.status.value if p else ChapterStatus.not_started.value),
                page_count=len(ch.pages),
                last_page_index=(p.last_page_index if p else 0),
            )
        )
    return out


@app.get("/api/chapters/{chapter_id}")
def api_chapter_detail(chapter_id: int) -> dict:
    ch = next((c for c in get_chapters() if c.id == chapter_id), None)
    if ch is None:
        raise HTTPException(404, f"chapter {chapter_id} not found")
    return ch.model_dump(mode="json")


# ---------------------------------------------------------------------------
# JSON API — grading
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    code: str
    timeout: float = 15.0


@app.post("/api/run")
def api_run(req: RunRequest) -> dict:
    """Execute arbitrary code in the kernel (Sample page Run button)."""
    res = get_kernel().execute(req.code, timeout=req.timeout)
    return {
        "status": res.status,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "error_name": res.error_name,
        "error_value": res.error_value,
        "traceback": list(res.traceback),
    }


class GradeRequest(BaseModel):
    chapter_id: int
    page_index: int
    values: dict[str, str] = {}            # exercise blanks
    selected_index: int | None = None      # reading multiple-choice


@app.post("/api/grade")
def api_grade(req: GradeRequest) -> dict:
    ch = next((c for c in get_chapters() if c.id == req.chapter_id), None)
    if ch is None:
        raise HTTPException(404, "chapter not found")
    if not (0 <= req.page_index < len(ch.pages)):
        raise HTTPException(400, "page_index out of range")
    page = ch.pages[req.page_index]

    if isinstance(page, ExercisePage):
        gr = grade_exercise(page, req.values, get_kernel())
    elif isinstance(page, ReadingPage):
        gr = grade_reading(page, req.selected_index)
    else:
        raise HTTPException(400, "page is not gradable")

    # Persist the submission attempt.
    repo = get_repo()
    repo.record_submission(
        user_id=get_user_id(),
        chapter_id=req.chapter_id,
        page_index=req.page_index,
        code=gr.assembled_code,
        passed=gr.overall_passed,
        stdout=(gr.execution.stdout if gr.execution else ""),
        stderr=(gr.execution.stderr if gr.execution else ""),
        hint_level_shown=0,
    )

    return {
        "overall_passed": gr.overall_passed,
        "failed_blanks": gr.failed_blanks,
        "assembled_code": gr.assembled_code,
        "execution": (
            {
                "status": gr.execution.status,
                "stdout": gr.execution.stdout,
                "stderr": gr.execution.stderr,
            }
            if gr.execution
            else None
        ),
        "test_results": [
            {"kind": r.kind, "passed": r.passed, "detail": r.detail}
            for r in gr.test_results
        ],
    }


# ---------------------------------------------------------------------------
# JSON API — progress
# ---------------------------------------------------------------------------


class ProgressUpdate(BaseModel):
    last_page_index: int
    completed: bool = False


@app.get("/api/progress")
def api_progress_all() -> list[dict]:
    repo = get_repo()
    rows = repo.all_progress(get_user_id())
    return [
        {
            "chapter_id": r.chapter_id,
            "status": r.status.value,
            "last_page_index": r.last_page_index,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@app.put("/api/progress/{chapter_id}")
def api_progress_upsert(chapter_id: int, body: ProgressUpdate) -> dict:
    repo = get_repo()
    repo.upsert_progress(
        user_id=get_user_id(),
        chapter_id=chapter_id,
        last_page_index=body.last_page_index,
        status=ChapterStatus.completed if body.completed else ChapterStatus.in_progress,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# JSON API — tests
# ---------------------------------------------------------------------------


@app.get("/api/tests")
def api_tests() -> list[dict]:
    return [
        {"id": ts.id, "title": ts.title, "phase": ts.phase,
         "questions": len(ts.questions),
         "time_limit_minutes": ts.time_limit_minutes,
         "pass_score": ts.pass_score}
        for ts in get_test_sets().values()
    ]


# ---------------------------------------------------------------------------
# JSON API — Ask AI
# ---------------------------------------------------------------------------


@app.get("/api/llm/available")
def api_llm_available() -> dict:
    """Tell the frontend whether the Ask AI button should be visible."""
    return {"available": get_llm().available}


# NOTE: a richer /api/llm/ask endpoint will be wired up alongside the
# result-page UI in a later phase. For now we only expose availability.


# ---------------------------------------------------------------------------
# Health check (used by main.py to know when uvicorn is ready)
# ---------------------------------------------------------------------------


@app.get("/api/ping")
def api_ping() -> JSONResponse:
    return JSONResponse({"ok": True})
