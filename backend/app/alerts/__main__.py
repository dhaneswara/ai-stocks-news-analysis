from __future__ import annotations

import argparse
import logging
import os
import sys

from app.alerts.notifier import build_notifier
from app.alerts.runner import run_alerts
from app.alerts.state import AlertState
from app.deps import DATA_DIR, DB_PATH, get_cache, get_settings_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.alerts", description="Run watchlist buy/sell alerts.")
    parser.add_argument("--dry-run", action="store_true", help="Log alerts instead of sending them.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM reasoning enrichment.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)

    settings = get_settings_store().load()
    cache = get_cache()
    state = AlertState(DB_PATH)
    notifier = build_notifier(settings.alerts, dry_run=args.dry_run)
    summary = run_alerts(settings, cache, state, notifier, with_llm=not args.no_llm)
    logging.getLogger("alerts").info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
