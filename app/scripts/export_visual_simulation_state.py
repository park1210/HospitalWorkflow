from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.core.logger import get_run_dir
from app.core.visual_simulation_state import build_visual_simulation_state


def export_visual_simulation_state(run_id: str) -> Path:
    state = build_visual_simulation_state(run_id)
    run_dir = get_run_dir(settings.REPORTS_DIR, run_id)
    output_path = run_dir / "visual_simulation_state.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return output_path


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.scripts.export_visual_simulation_state <run_id>")
        raise SystemExit(1)

    run_id = str(sys.argv[1]).strip()
    output_path = export_visual_simulation_state(run_id)
    print(f"[VISUAL_STATE] {output_path}")


if __name__ == "__main__":
    main()
