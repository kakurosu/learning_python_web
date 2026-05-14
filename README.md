# Study Python for Finance — Web UI Edition

This is the web-based UI rewrite of
[`kakurosu/learning_python`](https://github.com/kakurosu/learning_python).
The PyQt6 desktop UI from that repository has been swapped out for a
**FastAPI backend + HTML/CSS/JS frontend** wrapped in a `pywebview`
window. The result feels like a desktop app but the UI is rendered as a
modern web page, so styling / animation / typography are all easier to
get right.

## Architecture (high level)

```
pywebview window (OS WebView)
        |
        v
FastAPI + uvicorn  on  127.0.0.1:8765
        |
        v
Existing Python core (re-used from the PyQt6 version):
  app/content/   – YAML loader + Pydantic schemas
  app/db/        – SQLAlchemy progress.db
  app/grading/   – grade_exercise / grade_reading
  app/kernel/    – Jupyter KernelSession
  app/llm/       – Anthropic Claude wrapper
```

## Quick start

```bash
# 1. install
uv sync

# 2. run (opens a native window)
uv run python main.py
```

On Windows the window uses Edge WebView2 (preinstalled on Win10/11),
on macOS WKWebView, on Linux GTK WebKit. No additional runtime needs
to be installed.

## Status

Phase 0–3 done: project skeleton, FastAPI backend with 6 endpoints,
pywebview launcher, minimal Dashboard / Chapters templates. The
chapter list reads from the same 32 YAML files as the PyQt6 version.

Phases 4–8 (Sample / Reading / Exercise + Monaco / Tests / cleanup) are
the next work units — see `C:/Users/skokh/.claude/plans/` plan file.

## Relation to the PyQt6 version

PyQt6 codebase (`kakurosu/learning_python`) continues to be the stable
release. This repository is the experimental UI replacement. Backend
changes that should propagate (e.g. grading bug fixes) are synced
manually for now.
