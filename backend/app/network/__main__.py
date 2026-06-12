from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_cache, get_settings_store
from app.network.runner import run
from app.network.store import active_graph, get_active_ontology


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.network",
        description="Re-bake the active ontology's network signal into the board snapshot.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log what would bake, no save.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)
    settings = get_settings_store().load()
    cache = get_cache()
    log = logging.getLogger("network")
    if args.dry_run:
        g = active_graph(cache)
        log.info("Dry run: active=%s edges=%d", get_active_ontology(cache) or "(none)", len(g.edges))
        return 0
    log.info("Done: %s", run(settings, cache))
    return 0


if __name__ == "__main__":
    sys.exit(main())
