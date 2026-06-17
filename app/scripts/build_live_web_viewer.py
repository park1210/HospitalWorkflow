from __future__ import annotations

import sys
from pathlib import Path

from app.config import settings
from app.core.logger import get_latest_run_id, get_run_dir
from app.ui.web_viewer.builder import build_live_web_viewer_html


def build_live_web_viewer(run_id: str) -> Path:
    output_dir = get_run_dir(settings.REPORTS_DIR, run_id)
    output_path = output_dir / "live_web_viewer.html"
    output_path.write_text(
        build_live_web_viewer_html(run_id=run_id),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    run_id = str(sys.argv[1]).strip() if len(sys.argv) >= 2 and str(sys.argv[1]).strip() else get_latest_run_id(
        settings.REPORTS_DIR,
        required_file="live_visual_state.json",
    )
    output_path = build_live_web_viewer(run_id)
    print(output_path)


if __name__ == "__main__":
    main()
