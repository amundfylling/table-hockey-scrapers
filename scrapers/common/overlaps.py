"""Data from the sources the H2H site already ingests, used to skip events they cover."""

from __future__ import annotations

import io
import logging

import pandas as pd

log = logging.getLogger(__name__)

SPORTSCORPION_TOURNAMENTS_URL = (
    "https://raw.githubusercontent.com/amundfylling/Scorpion-Scraper-2.0/main/data/tournament_metadata.csv")
TABLE_HOCKEY_EU_URL = ("https://raw.githubusercontent.com/amundfylling/table-hockey-eu-fetch/refs/heads/main/"
                       "data/table_hockey_eu_results.parquet")


def sportscorpion_tournaments(client, country: str | None = None) -> pd.DataFrame:
    """Columns: TournamentID, Name, Country, Date, EndDate (dates as YYYY-MM-DD strings)."""
    resp = client.get(SPORTSCORPION_TOURNAMENTS_URL)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.content.decode("utf-8-sig")), dtype=str, keep_default_na=False)
    if country:
        df = df[df["Country"] == country]
    return df[["TournamentID", "Name", "Country", "Date", "EndDate"]].reset_index(drop=True)


def table_hockey_eu_tournaments(client) -> pd.DataFrame:
    """Columns: TournamentName, Date (first game date) of every tournament in table-hockey.eu's Parquet."""
    resp = client.get(TABLE_HOCKEY_EU_URL)
    resp.raise_for_status()
    df = pd.read_parquet(io.BytesIO(resp.content), columns=["TournamentID", "TournamentName", "Date"])
    return df.groupby("TournamentID", as_index=False).agg(TournamentName=("TournamentName", "first"),
                                                          Date=("Date", "min"))


def near_date(date: str, other: str, days: int = 1) -> bool:
    try:
        return abs((pd.Timestamp(date) - pd.Timestamp(other)).days) <= days
    except (ValueError, TypeError):
        return False
