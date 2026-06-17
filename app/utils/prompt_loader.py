from __future__ import annotations

from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=None)
def load_prompt(relative_path: str, fallback: str = "") -> str:
    prompt_path = settings.PROMPTS_DIR / relative_path
    if prompt_path.exists():
        content = prompt_path.read_text(encoding="utf-8").strip()
        if content:
            return content
    return fallback.strip()
