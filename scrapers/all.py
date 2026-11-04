"""Run every source with one shared player reference, then build all_results.parquet and the duplicate check.

    python -m scrapers.all [--only trefik,escore] [--offline]

A failing source is reported and the others still run; the previous Parquet of a failed source is kept and
still goes into all_results.parquet.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import traceback

import pandas as pd

from .common.context import add_common_args, build_context
from .common import id_report
from .common.dedupe import check_and_report
from .common.schema import COLUMNS, to_frame, write_parquet

ORDER = ["trefik", "galdahokejs", "escore", "finland"]
log = logging.getLogger("scrapers.all")


def combine(data_dir) -> pd.DataFrame:
    frames = []
    for name in ORDER:
        path = data_dir / f"{name}_results.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
    if not frames:
        return to_frame([])
    df = pd.concat(frames, ignore_index=True)[COLUMNS]
    return to_frame(df.to_dict("records"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scrapers.all")
    add_common_args(parser)
    parser.add_argument("--only", help="comma-separated subset of sources to crawl")
    parser.add_argument("--combine-only", action="store_true", help="skip crawling, only combine + check")
    args = parser.parse_args()
    ctx = build_context(args)
    selected = ORDER if not args.only else [s for s in ORDER if s in args.only.split(",")]
    failed = []
    if not args.combine_only:
        for name in selected:
            try:
                importlib.import_module(f"scrapers.{name}").run(ctx)
            except Exception:  # noqa: BLE001 - one source must not block the others
                failed.append(name)
                log.error("source %s failed:\n%s", name, traceback.format_exc())
    df = combine(ctx.data_dir)
    write_parquet(df, ctx.data_dir / "all_results.parquet")
    check_and_report(df, ctx.data_dir / "duplicate_check.csv")
    id_report.write(ctx.data_dir, ORDER, ctx.ref)
    if failed:
        print(f"\nFailed sources: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
