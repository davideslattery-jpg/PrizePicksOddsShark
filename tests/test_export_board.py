"""Board JSON shape expected by docs/app.js."""

from __future__ import annotations

import json
from pathlib import Path

from prizepicks_oddsshark.client import OddsClient
from prizepicks_oddsshark.export_util import BOARD_EDGE_KEYS, build_board, export_rows
from prizepicks_oddsshark.ranker import rank_edges

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REQUIRED_EDGE_KEYS = {
    "player",
    "market",
    "side",
    "pp_line",
    "book_line",
    "fair_prob",
    "offered_prob",
    "edge_pct",
    "game",
    "sport",
}


def test_demo_export_board_shape(tmp_path: Path):
    client = OddsClient(demo=True, fixtures_dir=FIXTURES)
    events = client.fetch_prop_events(
        "basketball_nba",
        ["player_points", "player_rebounds", "player_assists"],
        book="fanduel",
    )
    rows = rank_edges(
        events,
        book="fanduel",
        markets=["player_points", "player_rebounds", "player_assists"],
        min_edge=2.0,
    )
    out = tmp_path / "edges.json"
    export_rows(rows, out, sport="basketball_nba", book="fanduel", demo=True)
    board = json.loads(out.read_text(encoding="utf-8"))

    assert board["mode"] == "demo"
    assert board["book"] == "fanduel"
    assert "updated_at" in board and board["updated_at"].endswith("Z")
    assert board["sports"] == ["basketball_nba"]
    assert board["count"] == len(board["edges"]) == len(rows)
    assert board["edges"], "demo board should include edges"
    edge = board["edges"][0]
    missing = REQUIRED_EDGE_KEYS - set(edge)
    assert not missing, f"missing keys: {missing}"
    assert edge["game"]
    assert edge["sport"] == "basketball_nba"
    assert set(BOARD_EDGE_KEYS).issubset(edge.keys())


def test_build_board_empty():
    board = build_board([], sport="basketball_nba", demo=True)
    assert board["count"] == 0
    assert board["edges"] == []
    assert board["mode"] == "demo"
