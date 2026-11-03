"""Scraper for galdahokejs.lv. See README.md."""

from __future__ import annotations

import pandas as pd

from ..common.context import RunContext

SOURCE = "galdahokejs.lv"
OUTPUT = "galdahokejs_results.parquet"


def run(ctx: RunContext) -> pd.DataFrame:
    """Crawl (unless offline), transform the raw cache and write data/galdahokejs_results.parquet."""
    raise NotImplementedError(
        "galdahokejs: crawler/parser not written yet. The build environment could not reach galdahokejs.lv, and the "
        "parser must be written and tested against real pages saved from the site.")
