"""Prompt loading utilities for ER and specialty agents."""

from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = PROJECT_ROOT / "prompts"


BASE_PHYSICIAN_GUARD = (
    "You are a physician in a fictional hospital simulation. "
    "Use only the provided observations. "
    "Never assume unreleased results. "
    "Never use hidden evaluation labels. "
    "Every decision needs a brief evidence-based rationale."
)


@lru_cache(maxsize=None)
def _read_prompt(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"Prompt file not found: {path}"
        )

    text = path.read_text(
        encoding="utf-8"
    ).strip()

    if not text:
        raise ValueError(
            f"Prompt file is empty: {path}"
        )

    return text


def specialty_system_prompt(
    department: str,
) -> str:
    if (
        not isinstance(department, str)
        or not department.strip()
    ):
        raise ValueError(
            "Specialty department is required"
        )

    specialty_path = (
        PROMPT_ROOT
        / "specialty"
        / f"{department}.txt"
    )

    specialty_prompt = _read_prompt(
        specialty_path
    )

    return (
        BASE_PHYSICIAN_GUARD
        + "\n\n"
        + specialty_prompt
    )


def er_system_prompt() -> str:
    path = (
        PROMPT_ROOT
        / "er_department_system.txt"
    )

    if path.is_file():
        return (
            BASE_PHYSICIAN_GUARD
            + "\n\n"
            + _read_prompt(path)
        )

    return BASE_PHYSICIAN_GUARD