"""Load and validate chapter YAML files.

The loader is intentionally simple:
- One YAML file per chapter under ``content/chapters/NN_*.yaml``.
- Files are sorted by leading two-digit prefix.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .schemas import Chapter

_CHAPTER_FILE_RE = re.compile(r"^(\d{2})_.+\.ya?ml$", re.IGNORECASE)


class ContentError(RuntimeError):
    """Raised when chapter YAML cannot be parsed/validated."""


def load_chapter(path: Path) -> Chapter:
    """Load a single chapter YAML file and return a validated ``Chapter``."""
    text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ContentError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ContentError(f"{path}: top-level must be a mapping")
    try:
        return Chapter.model_validate(raw)
    except Exception as e:  # pydantic.ValidationError
        raise ContentError(f"Validation error in {path}: {e}") from e


def load_chapters(directory: Path) -> list[Chapter]:
    """Load every chapter YAML in a directory, sorted by file prefix."""
    if not directory.exists():
        raise ContentError(f"chapters directory not found: {directory}")
    files: list[tuple[int, Path]] = []
    for p in directory.iterdir():
        m = _CHAPTER_FILE_RE.match(p.name)
        if m:
            files.append((int(m.group(1)), p))
    files.sort(key=lambda t: t[0])
    chapters = [load_chapter(p) for _, p in files]
    # Sanity: chapter ids should be unique and equal to file prefix
    seen: set[int] = set()
    for prefix_pair, ch in zip(files, chapters):
        prefix, p = prefix_pair
        if ch.id != prefix:
            raise ContentError(
                f"{p.name}: chapter id={ch.id} does not match file prefix {prefix:02d}"
            )
        if ch.id in seen:
            raise ContentError(f"duplicate chapter id: {ch.id}")
        seen.add(ch.id)
    return chapters


def assemble_code(template: str, slot_values: dict[str, str]) -> str:
    """Replace ``{{slot:<id>}}`` placeholders in ``template`` with student input."""
    pattern = re.compile(r"\{\{slot:([^}\s]+)\}\}")

    def _sub(m: re.Match[str]) -> str:
        slot_id = m.group(1)
        if slot_id not in slot_values:
            raise KeyError(f"missing slot value for: {slot_id}")
        return slot_values[slot_id]

    return pattern.sub(_sub, template)
