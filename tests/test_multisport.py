"""Multi-sport parsing, markets, and board merge."""

from __future__ import annotations

import pytest

from prizepicks_oddsshark.export_util import build_board, merge_boards
from prizepicks_oddsshark.matching import (
    ALL_SPORTS,
    SUPPORTED_SPORTS,
    default_markets_for_sport,
    parse_sport_arg,
)
from prizepicks_oddsshark.ranker import RankedEdge


def test_parse_sport_all():
    sports = parse_sport_arg("all")
    assert sports == list(ALL_SPORTS)
    assert "basketball_nba" in sports
    assert "americanfootball_nfl" in sports
    assert "baseball_mlb" in sports
    assert "icehockey_nhl" in sports


def test_parse_sport_comma_list():
    sports = parse_sport_arg("basketball_nba, americanfootball_nfl, basketball_nba")
    assert sports == ["basketball_nba", "americanfootball_nfl"]


def test_parse_sport_unknown():
    with pytest.raises(ValueError, match="Unsupported"):
        parse_sport_arg("soccer_epl")


def test_default_markets_per_sport():
    assert "player_points" in default_markets_for_sport("basketball_nba")
    assert "player_pass_yds" in default_markets_for_sport("americanfootball_nfl")
    assert "batter_hits" in default_markets_for_sport("baseball_mlb")
    assert "pitcher_strikeouts" in default_markets_for_sport("baseball_mlb")
    assert "player_goals" in default_markets_for_sport("icehockey_nhl")
    assert "player_shots_on_goal" in default_markets_for_sport("icehockey_nhl")
    assert "player_points" in default_markets_for_sport("basketball_ncaab")
    assert "player_pass_yds" in default_markets_for_sport("americanfootball_ncaaf")
    for s in SUPPORTED_SPORTS:
        assert default_markets_for_sport(s)


def _edge(player: str, sport: str, edge: float) -> RankedEdge:
    return RankedEdge(
        player=player,
        market="player_points",
        side="Over",
        pp_line=20.5,
        book_line=20.5,
        line_diff=0.0,
        tier="standard",
        pp_price=None,
        book_price_over=-110,
        book_price_under=-110,
        fair_prob=0.55,
        offered_prob=0.5,
        edge_pct=edge,
        book="fanduel",
        event_id="e1",
        commence_time="2026-09-11T00:00:00Z",
        matchup="A @ B",
        adjusted=False,
        sport=sport,
    )


def test_merge_boards_sorts_by_edge():
    b1 = build_board([_edge("NBA Guy", "basketball_nba", 3.0)], sport="basketball_nba")
    b2 = build_board(
        [_edge("NFL Guy", "americanfootball_nfl", 5.5)],
        sport="americanfootball_nfl",
    )
    merged = merge_boards(b1, b2)
    assert merged["count"] == 2
    assert set(merged["sports"]) == {"basketball_nba", "americanfootball_nfl"}
    assert merged["edges"][0]["player"] == "NFL Guy"
    assert merged["edges"][0]["edge_pct"] == 5.5
    assert merged["edges"][1]["sport"] == "basketball_nba"


def test_build_board_mixed_sports_from_rows():
    rows = [
        _edge("A", "basketball_nba", 4.0),
        _edge("B", "baseball_mlb", 2.5),
    ]
    board = build_board(rows, book="fanduel", demo=False)
    assert board["sports"] == ["basketball_nba", "baseball_mlb"]
    assert board["edges"][0]["sport"] == "basketball_nba"
    assert board["edges"][1]["sport"] == "baseball_mlb"
