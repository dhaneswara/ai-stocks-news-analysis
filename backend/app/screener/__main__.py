from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_cache, get_settings_store
from app.screener.runner import run
from app.screener.service import run_scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.screener",
        description="Scan the universe and store a ranked opportunity board.",
    )
    parser.add_argument("--sector", default=None, help="Limit the scan to one GICS sector (default: all).")
    parser.add_argument("--dry-run", action="store_true", help="Scan and log the top names, but do not save.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)

    settings = get_settings_store().load()
    cache = get_cache()
    log = logging.getLogger("screener")
    if args.dry_run:
        board = run_scan(args.sector, settings, cache)
        log.info("Dry run: scope=%s scanned=%d skipped=%d top=%s",
                 board.scope, board.scanned, board.skipped, [i.ticker for i in board.items[:10]])
        return 0
    log.info("Done: %s", run(settings, cache, args.sector))
    return 0


if __name__ == "__main__":
    sys.exit(main())
