"""Request-local prompt folder.

Loaders read this folder when a profession sets it. If nothing is set, they
read prompts/doctor so a missed call cannot pick up creator text.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

DOCTOR_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "doctor"

_prompts_dir: ContextVar[Path | None] = ContextVar("profession_prompts_dir", default=None)


def current_prompts_dir() -> Path:
    current = _prompts_dir.get()
    if current is not None:
        return Path(current)
    return DOCTOR_PROMPTS_DIR


@contextmanager
def use_prompts(path: Path | None):
    token = _prompts_dir.set(Path(path) if path is not None else None)
    try:
        yield
    finally:
        _prompts_dir.reset(token)
