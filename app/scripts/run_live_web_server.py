from __future__ import annotations

import sys


def main() -> None:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Run: python -m pip install -r requirements.txt")
        raise SystemExit(1)

    host = "127.0.0.1"
    port = int(sys.argv[1]) if len(sys.argv) >= 2 and str(sys.argv[1]).strip() else 8010
    uvicorn.run("app.webapp.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
