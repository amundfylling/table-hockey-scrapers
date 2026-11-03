"""Scraper for escore.live. See README.md."""

from __future__ import annotations

import pandas as pd

from ..common.context import RunContext

SOURCE = "escore.live"
OUTPUT = "escore_results.parquet"


def run(ctx: RunContext) -> pd.DataFrame:
    """Crawl (unless offline), transform the raw cache and write data/escore_results.parquet."""
    raise NotImplementedError(
        "escore: crawler/parser not written yet. The build environment could not reach escore.live, and the "
        "parser must be written and tested against real pages saved from the site.")
