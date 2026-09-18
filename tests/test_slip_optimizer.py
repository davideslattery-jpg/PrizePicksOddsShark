"""Unit tests for Power/Flex slip EV + Sharpe math."""

from __future__ import annotations

import math

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
    # Certain hit → σ≈0 → sharpe guarded to 0
    assert row.sigma == pytest.approx(0.0)
    assert row.sharpe == pytest.approx(0.0)


def test_power_sharpe_analytic():
    """Power is two-point: hit→mult−1, miss→−1; Sharpe = EV / σ."""
    probs = [0.6, 0.55, 0.5]
    row = power_ev(probs)
    mult = POWER_MULTIPLIERS[3]
    p_all = 0.6 * 0.55 * 0.5
    ev = p_all * mult - 1.0
    profit_hit = mult - 1.0
    e_sq = p_all * profit_hit**2 + (1.0 - p_all) * 1.0
    var = e_sq - ev**2
    sigma = math.sqrt(max(var, 0.0))
    assert row.ev == pytest.approx(ev)
    assert row.sigma == pytest.approx(sigma)
    assert row.sharpe == pytest.approx(ev / sigma)
    assert row.sharpe != 0.0


def test_flex_three_enumeration():
    # Equal 0.5: P(3)=0.125 → 3x; P(exactly 2)=0.375 → 1x
    # E[pay] = 0.125*3 + 0.375*1 = 0.375+0.375=0.75; EV=-0.25
    row = flex_ev([0.5, 0.5, 0.5])
    assert row.label == "3 Flex"
    assert row.p_max == pytest.approx(0.125)
    assert row.p_cash == pytest.approx(0.125 + 0.375)
    assert row.expected_payout == pytest.approx(0.75)
    assert row.ev == pytest.approx(-0.25)
    # Moments: k=3 profit=2, k=2 profit=0, else −1
    # E[profit²] = 0.125*4 + 0.375*0 + 0.5*1 = 0.5+0.5=1.0
    # var = 1 - (-0.25)^2 = 0.9375; σ=√0.9375
    assert row.sigma == pytest.approx(math.sqrt(0.9375))
    assert row.sharpe == pytest.approx((-0.25) / math.sqrt(0.9375))


def test_rank_prefers_higher_ev():
    # High probs → Power often wins on EV for n=3
    ranked = rank_slip_types([0.7, 0.7, 0.7])
    assert ranked[0].ev >= ranked[-1].ev
    assert {r.kind for r in ranked} == {"power", "flex"}
    best = recommend_best([0.7, 0.7, 0.7])
    assert best.label == ranked[0].label


def test_rank_by_sharpe():
    ranked_ev = rank_slip_types([0.55, 0.55, 0.55, 0.55], rank="ev")
    ranked_sh = rank_slip_types([0.55, 0.55, 0.55, 0.55], rank="sharpe")
    assert ranked_sh[0].sharpe >= ranked_sh[-1].sharpe
    # Both metrics produce valid rows
    assert all(hasattr(r, "sharpe") for r in ranked_ev)


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


def _make_edges(n: int = 8):
    return [
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
            for i in range(n)
        ],
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


def test_suggest_slips_from_edges_ranks_and_filters_junk():
    from prizepicks_oddsshark.slip_optimizer import suggest_slips_from_edges

    result = suggest_slips_from_edges(
        _make_edges(8), platform="prizepicks", pool_size=12, top=5, rank="ev"
    )
    suggestions = result["ranked"]
    assert suggestions
    assert all(s["ev"] >= suggestions[-1]["ev"] for s in suggestions)
    assert all(2 <= s["n"] <= 6 for s in suggestions)
    assert all("sharpe" in s for s in suggestions)
    names = {p["player"] for s in suggestions for p in s["picks"]}
    assert "Junk Star" not in names
    assert "UD Only" not in names
    for i, a in enumerate(suggestions):
        for b in suggestions[i + 1 :]:
            if a["n"] != b["n"]:
                continue
            shared = len(set(a["keys"]) & set(b["keys"]))
            assert shared < a["n"] - 1 or a["n"] < 2


def test_suggest_best_by_n_and_sharpe_rank():
    from prizepicks_oddsshark.slip_optimizer import suggest_slips_from_edges

    result = suggest_slips_from_edges(
        _make_edges(8), platform="prizepicks", pool_size=12, top=6, rank="sharpe"
    )
    assert result["rank"] == "sharpe"
    ranked = result["ranked"]
    assert ranked
    assert all(s["sharpe"] >= ranked[-1]["sharpe"] for s in ranked)

    best_by_n = result["best_by_n"]
    assert best_by_n
    sizes = [s["n"] for s in best_by_n]
    assert sizes == sorted(sizes)
    assert all(n in (3, 4, 5, 6) for n in sizes)
    # Mix of sizes when pool is large enough
    assert len(set(sizes)) >= 2
    # Each best_by_n row beats other same-n options on sharpe within ranked pool logic:
    # at least one Power or Flex label present across sizes
    assert any("Power" in s["label"] or "Flex" in s["label"] for s in best_by_n)


def test_suggest_mix_of_sizes_in_ranked():
    from prizepicks_oddsshark.slip_optimizer import suggest_slips_from_edges

    # Without diversify, ranked by EV often includes large Power; with pool of 8
    # we still get best_by_n covering 3–6 when possible.
    result = suggest_slips_from_edges(
        _make_edges(8),
        platform="prizepicks",
        pool_size=8,
        top=10,
        diversify=False,
        rank="ev",
    )
    ns = {s["n"] for s in result["best_by_n"]}
    assert ns == {3, 4, 5, 6}
    # Ranked list should include more than one size when diversify off + enough combos
    ranked_ns = {s["n"] for s in result["ranked"]}
    assert len(ranked_ns) >= 2 or len(result["ranked"]) < 2
