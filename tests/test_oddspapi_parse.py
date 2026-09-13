"""Offline OddsPapi response → Odds API event shape + ranking."""

from __future__ import annotations

import json
from pathlib import Path

from prizepicks_oddsshark.oddspapi_client import (
    OddsPapiClient,
    map_market_name,
    normalize_player_name,
)
from prizepicks_oddsshark.ranker import rank_edges

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE = FIXTURES / "oddspapi" / "nfl_sample.json"


def test_map_market_name_nba_nfl():
    assert map_market_name("Over Under Player Points (incl. overtime)") == "player_points"
    assert map_market_name("Over Under Player Assists (incl. overtime)") == "player_assists"
    assert map_market_name("Over Under Pass Yards (incl. overtime)") == "player_pass_yds"
    assert map_market_name("Over Under Rush Yards (incl. overtime)") == "player_rush_yds"
    assert (
        map_market_name("Over Under Player Receiving Yards (incl. overtime)")
        == "player_reception_yds"
    )
    assert map_market_name("Over Under Player Receptions (incl. overtime)") == "player_receptions"
    assert map_market_name("Over Under Player TD Passes (incl. overtime)") == "player_pass_tds"
    assert map_market_name("Over Under Player Points First Quarter") is None
    assert map_market_name("Over Under Longest Rush Yards (incl. overtime)") is None


def test_normalize_player_name():
    assert normalize_player_name("Mahomes, Patrick") == "Patrick Mahomes"
    assert normalize_player_name("Patrick Mahomes") == "Patrick Mahomes"
    assert normalize_player_name("") == ""


def test_odds_to_event_and_rank_offline():
    payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
    client = OddsPapiClient(demo=True, fixtures_dir=FIXTURES)
    # Inject markets catalog from fixture without HTTP
    client._markets_by_id = {int(m["marketId"]): m for m in payload["markets"]}
    client._outcome_name = {}
    for m in payload["markets"]:
        for o in m.get("outcomes") or []:
            client._outcome_name[int(o["outcomeId"])] = str(o.get("outcomeName") or "")

    event = client.odds_to_event(
        payload["odds"],
        sport="americanfootball_nfl",
        market_filter=[
            "player_pass_yds",
            "player_rush_yds",
            "player_reception_yds",
            "player_receptions",
            "player_pass_tds",
        ],
        bookmakers=["prizepicks", "fanduel"],
    )
    assert event["id"]
    assert event["sport_key"] == "americanfootball_nfl"
    books = {b["key"] for b in event["bookmakers"]}
    assert "fanduel" in books and "prizepicks" in books
    # Outcomes use First Last + Over/Under + point
    fd = next(b for b in event["bookmakers"] if b["key"] == "fanduel")
    assert fd["markets"]
    sample_out = fd["markets"][0]["outcomes"][0]
    assert sample_out["name"] in ("Over", "Under")
    assert "," not in sample_out["description"]
    assert sample_out["point"] is not None

    rows = rank_edges(
        [event],
        book="fanduel",
        markets=[
            "player_pass_yds",
            "player_rush_yds",
            "player_reception_yds",
            "player_receptions",
            "player_pass_tds",
        ],
        min_edge=0.0,
        sport="americanfootball_nfl",
    )
    assert isinstance(rows, list)
    # Synthetic PP at -110 vs FD should produce some edges at min_edge 0
    assert rows, "expected ranked edges from canned OddsPapi fixture"


def test_fetch_prop_events_demo_oddspapi():
    client = OddsPapiClient(demo=True, fixtures_dir=FIXTURES)
    events = client.fetch_prop_events(
        "americanfootball_nfl",
        ["player_reception_yds", "player_rush_yds", "player_receptions"],
        book="fanduel",
        max_events=1,
    )
    assert len(events) == 1
    assert events[0]["bookmakers"]
