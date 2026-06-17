from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.ui.pixel_viewer import runtime


@dataclass(frozen=True)
class PixelViewerConfig:
    package: str = "app.ui.pixel_viewer"
    runtime_module: str = "app.ui.pixel_viewer.runtime"


def run(argv: Sequence[str] | None = None) -> int:
    runtime.main(list(argv) if argv is not None else None)
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
