"""The committed Parquets (what the H2H site downloads) pass the audit checks."""

from pathlib import Path

import pandas as pd
import pytest

from scrapers.common.checks import carried_over_stages, double_slot_conflicts, shared_id_conflicts

DATA = Path(__file__).resolve().parents[2] / "data"
FILES = [p for p in (DATA / f"{s}_results.parquet" for s in ("trefik", "galdahokejs", "escore", "finland"))
         if p.exists()]


@pytest.fixture(scope="module", params=FILES, ids=lambda p: p.stem)
def df(request):
    return pd.read_parquet(request.param)


def test_no_id_with_two_unrelated_names_in_one_tournament(df):
    assert shared_id_conflicts(df) == []


def test_no_id_in_two_rows_of_one_group(df):
    assert double_slot_conflicts(df) == []


def test_no_tournament_stores_carried_over_games_in_a_final_group(df):
    # A same pair + same score in a basic and a final group is allowed only as a coincidence among real
    # rematches; a final-group stage where most earlier pairs repeat their score is a stored copy.
    assert carried_over_stages(df) == []


def test_new_columns(df):
    assert {"Country", "City", "Walkover"} <= set(df.columns)
    assert df["Country"].notna().all()
    assert df["Walkover"].isin(["Yes", "No"]).all()
