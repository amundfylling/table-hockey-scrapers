"""Finland: event index -> sub-tournaments (results need access, see README)."""

import json
from pathlib import Path

from scrapers.finland import sub_tournaments

FIX = Path(__file__).parent / "fixtures"


def test_sub_tournaments_from_real_index():
    events = json.loads((FIX / "events_sample.json").read_text(encoding="utf-8"))["events"]
    subs = sub_tournaments(events)
    assert sorted(s["name"] for s in subs) == [
        "215. Tampere", "215. Tampere – Haastajasarja", "215. Tampere – Juniors", "215. Tampere – Veterans"]
    assert all(s["date"] == "2026-10-17" for s in subs)
    assert {s["event_slug"] for s in subs} == {events[0]["slug"]}  # the SCHEDULED event is left out
