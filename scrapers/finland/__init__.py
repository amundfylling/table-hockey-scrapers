"""Scraper for tulos.poytajaakiekko.fi. See README.md."""

from __future__ import annotations

import pandas as pd

from ..common.context import RunContext

SOURCE = "tulos.poytajaakiekko.fi"
OUTPUT = "finland_results.parquet"


def run(ctx: RunContext) -> pd.DataFrame:
    """Crawl (unless offline), transform the raw cache and write data/finland_results.parquet."""
    raise NotImplementedError(
        "finland: crawler/parser not written yet. The build environment could not reach tulos.poytajaakiekko.fi, and the "
        "parser must be written and tested against real pages saved from the site.")
