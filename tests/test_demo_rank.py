import json
from pathlib import Path

from prizepicks_oddsshark.client import OddsClient
from prizepicks_oddsshark.ranker import rank_edges

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_demo_client_loads_fixtures():
    client = OddsClient(demo=True, fixtures_dir=FIXTURES)
    events = client.list_events("basketball_nba")
    assert isinstance(events, list) and events
    odds = client.event_odds(
        "basketball_nba",
        events[0]["id"],
        regions="us,us_dfs",
        markets="player_points",
    )
    assert odds["id"] == events[0]["id"]
    books = {b["key"] for b in odds["bookmakers"]}
    assert "fanduel" in books and "prizepicks" in books


def test_rank_edges_offline_from_fixture():
    payload = json.loads((FIXTURES / "event_odds_nba.json").read_text(encoding="utf-8"))
    rows = rank_edges(
        [payload],
        book="fanduel",
        markets=["player_points", "player_rebounds", "player_assists"],
        min_edge=0.0,
    )
    assert rows, "expected at least one ranked row from fixture"
    assert rows[0].edge_pct >= rows[-1].edge_pct
    # LeBron Over 24.5 should have positive edge vs 50% (FD -130/-ish)
    lebron_over = [
        r
        for r in rows
        if r.player == "LeBron James" and r.side == "Over" and r.tier == "standard" and r.pp_line == 24.5
    ]
    assert lebron_over
    assert lebron_over[0].fair_prob > 0.5
    assert lebron_over[0].edge_pct > 0


def test_fetch_prop_events_demo():
    client = OddsClient(demo=True, fixtures_dir=FIXTURES)
    events = client.fetch_prop_events(
        "basketball_nba",
        ["player_points"],
        book="fanduel",
    )
    assert len(events) == 1
    rows = rank_edges(events, book="fanduel", markets=["player_points"], min_edge=2.0)
    assert isinstance(rows, list)
