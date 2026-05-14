"""Process-wide singletons (Repository, KernelSession, ClaudeClient).

Created lazily so that ``uvicorn --reload`` works without surprises and
so that tests can swap them out via fastapi dependency overrides.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.content.loader import ContentError, load_chapters
from app.content.test_schemas import load_test_sets
from app.db.repo import Repository
from app.kernel.manager import KernelSession
from app.llm.claude_client import ClaudeClient

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHAPTERS_DIR = PROJECT_ROOT / "content" / "chapters"
TESTS_DIR = PROJECT_ROOT / "content" / "tests"
DB_PATH = PROJECT_ROOT / "progress.db"


@lru_cache(maxsize=1)
def get_repo() -> Repository:
    return Repository(DB_PATH)


@lru_cache(maxsize=1)
def get_kernel() -> KernelSession:
    k = KernelSession()
    try:
        k.start()
    except Exception:  # noqa: BLE001
        log.exception("kernel start failed")
    return k


@lru_cache(maxsize=1)
def get_llm() -> ClaudeClient:
    return ClaudeClient()


@lru_cache(maxsize=1)
def get_chapters() -> list:
    try:
        return load_chapters(CHAPTERS_DIR)
    except ContentError:
        log.exception("chapter load failed")
        return []


@lru_cache(maxsize=1)
def get_test_sets() -> dict:
    try:
        return load_test_sets(TESTS_DIR)
    except Exception:  # noqa: BLE001
        log.exception("test set load failed")
        return {}


def get_user_id() -> int:
    """Default single-user id. Stays simple while the app is local-only."""
    return get_repo().get_or_create_default_user().id
