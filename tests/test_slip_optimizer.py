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
