from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from scrapers.common.schema import COLUMNS, SchemaError, to_frame, validate, write_parquet

FIX = Path(__file__).parent / "fixtures"


def test_roundtrip_matches_reference_schema(tmp_path):
    # Real rows from table-hockey-eu-fetch's Parquet: our writer must produce the identical Arrow schema.
    ref_path = FIX / "table_hockey_eu_sample.parquet"
    ref = pd.read_parquet(ref_path)
    out = tmp_path / "out.parquet"
    write_parquet(to_frame(ref.to_dict("records")), out)
    assert pq.read_schema(out).names == pq.read_schema(ref_path).names == COLUMNS
    assert pq.read_schema(out).types == pq.read_schema(ref_path).types
    back = pd.read_parquet(out)
    assert [str(t) for t in back.dtypes] == [str(t) for t in ref.dtypes]


def _row(**kw):
    base = dict(StageID=1, Player1="A B", Player1ID=1, Player2="C D", Player2ID=2, GoalsPlayer1=3, GoalsPlayer2=3,
                Overtime="No", Stage="Basic groups 1", RoundNumber=None, PlayoffGameNumber=None, Date="2025-01-02",
                TournamentName="T", TournamentID=10, StageSequence=1, StageType="roundrobin", Source="s",
                SourceTournamentID="t", SourceStageID="g", SourceMatchID="m1")
    base.update(kw)
    return base


def test_sorting_is_deterministic():
    rows = [_row(SourceMatchID="b", Date="2025-01-02"), _row(SourceMatchID="a", Date="2025-01-02"),
            _row(SourceMatchID="c", Date="2024-12-31")]
    df = to_frame(rows)
    assert df["SourceMatchID"].tolist() == ["c", "a", "b"]
    validate(df)  # draws are fine


@pytest.mark.parametrize("bad", [
    {"Overtime": "P"}, {"StageType": "groups"}, {"Date": "22.04.2023"}, {"Player2ID": 1},
    {"GoalsPlayer1": None},
])
def test_validate_rejects(bad):
    with pytest.raises(SchemaError):
        validate(to_frame([_row(**bad)]))


def test_validate_rejects_duplicate_match_ids():
    with pytest.raises(SchemaError):
        validate(to_frame([_row(), _row()]))
