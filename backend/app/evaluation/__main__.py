from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_prediction_store, get_settings_store
from app.evaluation.runner import run_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation",
        description="Score matured LLM recommendations against actual price moves.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute scores without persisting them.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)

    settings = get_settings_store().load()
    store = get_prediction_store()
    summary = run_evaluation(store, settings, dry_run=args.dry_run)
    logging.getLogger("evaluation").info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
