"""The output schema shared with bordshockey.net-scraper and table-hockey-eu-fetch, and the Parquet writer."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

log = logging.getLogger(__name__)

# Column order and dtypes are identical to bordshockey_results.parquet / table_hockey_eu_results.parquet.
SCHEMA: dict[str, str] = {
    "StageID": "Int64",
    "Player1": "string",
    "Player1ID": "Int64",
    "Player2": "string",
    "Player2ID": "Int64",
    "GoalsPlayer1": "Int64",
    "GoalsPlayer2": "Int64",
    "Overtime": "string",
    "Stage": "string",
    "RoundNumber": "Int64",
    "PlayoffGameNumber": "Int64",
    "Date": "string",
    "TournamentName": "string",
    "TournamentID": "Int64",
    "StageSequence": "Int64",
    "StageType": "string",
    "TournamentURL": "string",
    "ResultURL": "string",
    "StageURL": "string",
    "SourceURL": "string",
    "Source": "string",
    "SourceTournamentID": "string",
    "SourceStageID": "string",
    "SourceMatchID": "string",
}
BASE_COLUMNS = list(SCHEMA)
# Columns this repo adds after the shared ones (the H2H site ignores columns it does not know):
# Country / City of the event, Walkover = "Yes" for a game the page marks as a forfeit (score is the forfeit score).
EXTRA_SCHEMA: dict[str, str] = {"Country": "string", "City": "string", "Walkover": "string"}
SCHEMA = {**SCHEMA, **EXTRA_SCHEMA}
COLUMNS = list(SCHEMA)
SORT_KEYS = ["Date", "TournamentID", "StageSequence", "RoundNumber", "SourceMatchID"]
REQUIRED = [
    "StageID", "Player1", "Player1ID", "Player2", "Player2ID", "GoalsPlayer1", "GoalsPlayer2", "Overtime",
    "Stage", "Date", "TournamentName", "TournamentID", "StageSequence", "StageType", "Source",
    "SourceTournamentID", "SourceStageID", "SourceMatchID",
]
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SchemaError(ValueError):
    pass


def to_frame(rows: Iterable[Mapping]) -> pd.DataFrame:
    """Build a DataFrame in the exact schema and the deterministic sort order."""
    df = pd.DataFrame(list(rows))
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = "No" if col == "Walkover" else pd.NA
    df = df[COLUMNS]
    df["Walkover"] = df["Walkover"].where(df["Walkover"].notna(), "No")
    for col, dtype in SCHEMA.items():
        df[col] = df[col].astype(dtype)
    df = df.sort_values(SORT_KEYS, kind="mergesort", na_position="first").reset_index(drop=True)
    return df


def validate(df: pd.DataFrame) -> None:
    if list(df.columns) != COLUMNS:
        raise SchemaError(f"column order differs: {list(df.columns)}")
    for col, dtype in SCHEMA.items():
        if str(df[col].dtype) != dtype:
            raise SchemaError(f"{col} has dtype {df[col].dtype}, expected {dtype}")
    if df.empty:
        return
    for col in REQUIRED:
        if df[col].isna().any():
            raise SchemaError(f"{col} has {int(df[col].isna().sum())} missing values")
    if not df["Overtime"].isin(["Yes", "No"]).all():
        raise SchemaError("Overtime must be Yes/No")
    if not df["Walkover"].isin(["Yes", "No"]).all():
        raise SchemaError("Walkover must be Yes/No")
    if df["Country"].isna().any():
        raise SchemaError("Country missing")
    if not df["StageType"].isin(["roundrobin", "playoff"]).all():
        raise SchemaError("StageType must be roundrobin/playoff")
    if not df["Date"].str.match(_DATE).all():
        raise SchemaError("Date must be YYYY-MM-DD")
    if ((df["GoalsPlayer1"] < 0) | (df["GoalsPlayer2"] < 0)).any():
        raise SchemaError("negative goals")
    if (df["Player1ID"] == df["Player2ID"]).any():
        raise SchemaError("a player plays themself")
    dup = df.duplicated(["Source", "SourceMatchID"])
    if dup.any():
        raise SchemaError(f"SourceMatchID not unique: {df.loc[dup, 'SourceMatchID'].head().tolist()}")
    po = df["StageType"] == "playoff"
    if df.loc[~po, "PlayoffGameNumber"].notna().any():
        raise SchemaError("round-robin rows must have no PlayoffGameNumber")


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    validate(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    log.info("wrote %s rows to %s", len(df), path)
