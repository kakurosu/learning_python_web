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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.content.schemas import Chapter, ExercisePage, ReadingPage
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
    return templates.TemplateResponse(
        request, "dashboard.html", {"active": "dashboard"}
    )


@app.get("/chapters", response_class=HTMLResponse)
def page_chapters(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "chapters.html", {"active": "chapters"}
    )


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
