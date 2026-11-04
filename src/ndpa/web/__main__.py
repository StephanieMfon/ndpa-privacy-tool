"""python -m ndpa.web  (run from the repository root)"""
import argparse
from pathlib import Path

import uvicorn

from ndpa.storage import db
from ndpa.web.app import create_app
from ndpa.web.jobs import Settings


def main() -> None:
    ap = argparse.ArgumentParser(description="Start the NDPA Privacy Check dashboard.")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 only inside a container")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--vantage", default="unspecified", help='where scans run from, e.g. "Port Harcourt, NG"')
    ap.add_argument("--headless", action="store_true", help="run Chrome without a visible window")
    ap.add_argument("--bundled-chromium", action="store_true")
    ap.add_argument("--observe", type=float, default=10.0)
    args = ap.parse_args()
    settings = Settings(db_path=Path(args.db), vantage=args.vantage, headless=args.headless,
                        bundled_chromium=args.bundled_chromium, observe_s=args.observe)
    print(f"NDPA Privacy Check: http://{args.host}:{args.port}  (scans run from: {args.vantage})")
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
