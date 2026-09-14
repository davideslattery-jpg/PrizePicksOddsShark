"""Dual DFS (PrizePicks + Underdog) tagging, ranking, and board export."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from prizepicks_oddsshark.client import OddsClient
from prizepicks_oddsshark.export_util import build_board, export_rows
from prizepicks_oddsshark.matching import DFS_BOOKMAKERS, extract_props_from_event
from prizepicks_oddsshark.ranker import parse_dfs_arg, rank_edges

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _event_with_underdog() -> dict:
    """Clone NBA demo fixture and mirror PrizePicks markets as Underdog."""
    payload = json.loads((FIXTURES / "event_odds_nba.json").read_text(encoding="utf-8"))
    event = copy.deepcopy(payload)
    pp = next(b for b in event["bookmakers"] if b["key"] == "prizepicks")
    underdog = copy.deepcopy(pp)
    underdog["key"] = "underdog"
    underdog["title"] = "Underdog Fantasy"
    # Slightly different line so edges are distinguishable
    for market in underdog.get("markets") or []:
        for outcome in market.get("outcomes") or []:
            if outcome.get("description") == "LeBron James" and outcome.get("name") == "Over":
                if market.get("key") == "player_points":
                    outcome["point"] = 23.5  # better line vs FD 24.5
    event["bookmakers"].append(underdog)
    return event


def test_parse_dfs_arg():
    assert parse_dfs_arg("both") == ["prizepicks", "underdog"]
    assert parse_dfs_arg(None) == ["prizepicks", "underdog"]
    assert parse_dfs_arg("prizepicks") == ["prizepicks"]
    assert parse_dfs_arg("underdog") == ["underdog"]
    assert parse_dfs_arg("prizepicks,underdog") == ["prizepicks", "underdog"]
    with pytest.raises(ValueError):
        parse_dfs_arg("draftkings")


def test_dfs_bookmakers_constant():
    assert DFS_BOOKMAKERS == frozenset({"prizepicks", "underdog"})


def test_rank_edges_tags_platform():
    event = _event_with_underdog()
    rows = rank_edges(
        [event],
        book="fanduel",
        markets=["player_points", "player_rebounds", "player_assists"],
        min_edge=0.0,
        dfs_platforms=["prizepicks", "underdog"],
    )
    platforms = {r.platform for r in rows}
    assert "prizepicks" in platforms
    assert "underdog" in platforms
    pp_only = rank_edges(
        [event],
        book="fanduel",
        markets=["player_points"],
        min_edge=0.0,
        dfs_platforms=["prizepicks"],
    )
    assert pp_only and all(r.platform == "prizepicks" for r in pp_only)
    ud_only = rank_edges(
        [event],
        book="fanduel",
        markets=["player_points"],
        min_edge=0.0,
        dfs_platforms=["underdog"],
    )
    assert ud_only and all(r.platform == "underdog" for r in ud_only)


def test_extract_props_underdog_tier():
    event = _event_with_underdog()
    legs = extract_props_from_event(event, bookmaker_keys=["underdog"])
    assert legs
    assert all(leg.bookmaker == "underdog" for leg in legs)
    assert all(leg.tier is not None for leg in legs)


def test_board_export_has_dfs_platforms(tmp_path: Path):
    event = _event_with_underdog()
    rows = rank_edges(
        [event],
        book="fanduel",
        markets=["player_points"],
        min_edge=0.0,
        dfs_platforms=["prizepicks", "underdog"],
        sport="basketball_nba",
    )
    out = tmp_path / "edges.json"
    export_rows(
        rows,
        out,
        sport="basketball_nba",
        book="fanduel",
        demo=True,
        dfs_platforms=["prizepicks", "underdog"],
    )
    board = json.loads(out.read_text(encoding="utf-8"))
    assert board["dfs_platforms"] == ["prizepicks", "underdog"]
    assert board["count"] == len(board["edges"])
    assert {e["platform"] for e in board["edges"]} == {"prizepicks", "underdog"}
    for e in board["edges"]:
        assert "platform" in e


def test_board_filter_client_side_compat():
    """Board UI filters by platform field; missing platform defaults to prizepicks."""
    board = build_board([], sport="basketball_nba", demo=True, dfs_platforms=["prizepicks", "underdog"])
    assert board["dfs_platforms"] == ["prizepicks", "underdog"]
    assert board["edges"] == []


def test_demo_fetch_still_works_with_dfs_both():
    client = OddsClient(demo=True, fixtures_dir=FIXTURES)
    events = client.fetch_prop_events(
        "basketball_nba",
        ["player_points"],
        book="fanduel",
        dfs="both",
    )
    assert len(events) == 1
    # Demo fixture has prizepicks only — ranking both still yields PP edges
    rows = rank_edges(
        events,
        book="fanduel",
        markets=["player_points"],
        min_edge=0.0,
        dfs_platforms=["prizepicks", "underdog"],
    )
    assert rows
    assert all(r.platform == "prizepicks" for r in rows)


def test_client_bookmakers_string_includes_underdog():
    """Live path builds fanduel,prizepicks,underdog in one call (inspected via source)."""
    src = Path(__file__).resolve().parents[1] / "src" / "prizepicks_oddsshark" / "client.py"
    text = src.read_text(encoding="utf-8")
    assert "us,us_dfs" in text
    assert "dfs_part" in text
    assert 'books = f"{book},{dfs_part}"' in text
