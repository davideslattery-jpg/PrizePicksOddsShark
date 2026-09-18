"""Unit tests for Power/Flex slip EV math."""

from __future__ import annotations

import pytest

from prizepicks_oddsshark.slip_optimizer import (
    POWER_MULTIPLIERS,
    flex_ev,
    power_ev,
    probs_from_board_edges,
    rank_slip_types,
    recommend_best,
)


def test_power_two_known():
    # p=0.5,0.5 → P(both)=0.25; 3x → E[pay]=0.75; EV=-0.25
    row = power_ev([0.5, 0.5])
    assert row.label == "2 Power"
    assert row.p_max == pytest.approx(0.25)
    assert row.expected_payout == pytest.approx(0.75)
    assert row.ev == pytest.approx(-0.25)


def test_power_three_multiplier():
    assert POWER_MULTIPLIERS[3] == 6.0
    row = power_ev([1.0, 1.0, 1.0])
    assert row.ev == pytest.approx(5.0)  # 6x - 1


def test_flex_three_enumeration():
    # Equal 0.5: P(3)=0.125 → 3x; P(exactly 2)=0.375 → 1x
    # E[pay] = 0.125*3 + 0.375*1 = 0.375+0.375=0.75; EV=-0.25
    row = flex_ev([0.5, 0.5, 0.5])
    assert row.label == "3 Flex"
    assert row.p_max == pytest.approx(0.125)
    assert row.p_cash == pytest.approx(0.125 + 0.375)
    assert row.expected_payout == pytest.approx(0.75)
    assert row.ev == pytest.approx(-0.25)


def test_rank_prefers_higher_ev():
    # High probs → Power often wins on EV for n=3
    ranked = rank_slip_types([0.7, 0.7, 0.7])
    assert ranked[0].ev >= ranked[-1].ev
    assert {r.kind for r in ranked} == {"power", "flex"}
    best = recommend_best([0.7, 0.7, 0.7])
    assert best.label == ranked[0].label


def test_probs_from_board():
    edges = [
        {"edge_pct": 5.0, "fair_prob": 0.6},
        {"edge_pct": 4.0, "fair_prob": 0.55},
        {"edge_pct": 3.0, "fair_prob": 0.52},
        {"edge_pct": 2.0, "fair_prob": 0.51},
    ]
    assert probs_from_board_edges(edges, top=3) == [0.6, 0.55, 0.52]


def test_rejects_bad_n():
    with pytest.raises(ValueError):
        rank_slip_types([0.5])
    with pytest.raises(ValueError):
        rank_slip_types([0.5] * 7)


def test_is_junk_edge_rules():
    from prizepicks_oddsshark.slip_optimizer import is_junk_edge

    assert is_junk_edge({"fair_prob": None, "edge_pct": 3}) is True
    assert is_junk_edge({"fair_prob": 1.0, "edge_pct": 3}) is True
    assert is_junk_edge({"fair_prob": 0.55, "edge_pct": 16, "line_diff": 1}) is True
    assert is_junk_edge({"fair_prob": 0.55, "edge_pct": 5, "line_diff": 6}) is True
    assert is_junk_edge({"fair_prob": 0.55, "edge_pct": 5, "line_diff": 1}) is False


def test_suggest_slips_from_edges_ranks_and_filters_junk():
    from prizepicks_oddsshark.slip_optimizer import suggest_slips_from_edges

    edges = [
        # junk: absurd edge
        {
            "platform": "prizepicks",
            "event_id": "j1",
            "player": "Junk Star",
            "market": "player_points",
            "side": "Over",
            "pp_line": 20,
            "tier": "standard",
            "edge_pct": 49.0,
            "line_diff": -6.0,
            "fair_prob": 0.99,
        },
        # solid candidates
        *[
            {
                "platform": "prizepicks",
                "event_id": f"e{i}",
                "player": f"Player {i}",
                "market": "player_points",
                "side": "Over",
                "pp_line": 10 + i,
                "tier": "standard",
                "edge_pct": 10 - i * 0.5,
                "line_diff": 1.0,
                "fair_prob": 0.58 - i * 0.01,
            }
            for i in range(8)
        ],
        # underdog should be ignored when platform=prizepicks
        {
            "platform": "underdog",
            "event_id": "u1",
            "player": "UD Only",
            "market": "player_points",
            "side": "Over",
            "pp_line": 5,
            "tier": "standard",
            "edge_pct": 14.0,
            "line_diff": 0.5,
            "fair_prob": 0.62,
        },
    ]
    suggestions = suggest_slips_from_edges(
        edges, platform="prizepicks", pool_size=12, top=5
    )
    assert suggestions
    assert all(s["ev"] >= suggestions[-1]["ev"] for s in suggestions)
    assert all(2 <= s["n"] <= 6 for s in suggestions)
    names = {p["player"] for s in suggestions for p in s["picks"]}
    assert "Junk Star" not in names
    assert "UD Only" not in names
    # diversity: no two same-size slips share n-1 legs
    for i, a in enumerate(suggestions):
        for b in suggestions[i + 1 :]:
            if a["n"] != b["n"]:
                continue
            shared = len(set(a["keys"]) & set(b["keys"]))
            assert shared < a["n"] - 1 or a["n"] < 2
