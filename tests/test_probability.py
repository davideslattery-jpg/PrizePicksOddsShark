import math

import pytest

from prizepicks_oddsshark.probability import (
    american_to_implied,
    edge_pct,
    fair_probs_from_american,
    line_adjusted_prob,
    multiplicative_devig,
    offered_prob_for_prizepicks,
)


def test_american_negative():
    # -110 → 110/210 ≈ 0.5238
    assert american_to_implied(-110) == pytest.approx(110 / 210, rel=1e-6)


def test_american_positive():
    # +150 → 100/250 = 0.4
    assert american_to_implied(150) == pytest.approx(0.4)


def test_american_even():
    assert american_to_implied(100) == pytest.approx(0.5)


def test_american_zero_raises():
    with pytest.raises(ValueError):
        american_to_implied(0)


def test_multiplicative_devig_sums_to_one():
    a, b = multiplicative_devig(0.55, 0.55)
    assert a + b == pytest.approx(1.0)
    assert a == pytest.approx(0.5)


def test_fair_probs_from_minus_110():
    o, u = fair_probs_from_american(-110, -110)
    assert o + u == pytest.approx(1.0)
    assert o == pytest.approx(0.5)


def test_fair_probs_favored_over():
    o, u = fair_probs_from_american(-130, 110)
    assert o + u == pytest.approx(1.0)
    assert o > 0.5 > u


def test_line_adjust_higher_line_lowers_over_prob():
    # At book line fair over ~0.55; raising line should reduce P(over)
    base = 0.55
    adj = line_adjusted_prob(base, book_line=24.5, target_line=28.5, side="Over")
    assert adj < base


def test_line_adjust_lower_line_raises_over_prob():
    base = 0.55
    adj = line_adjusted_prob(base, book_line=24.5, target_line=20.5, side="Over")
    assert adj > base


def test_line_adjust_under_is_complement():
    base = 0.55
    over = line_adjusted_prob(base, book_line=24.5, target_line=26.5, side="Over")
    under = line_adjusted_prob(base, book_line=24.5, target_line=26.5, side="Under")
    assert over + under == pytest.approx(1.0, abs=1e-6)


def test_same_line_no_change():
    base = 0.52
    adj = line_adjusted_prob(base, book_line=24.5, target_line=24.5, side="Over")
    assert adj == pytest.approx(base, abs=1e-4)


def test_offered_standard_is_half():
    assert offered_prob_for_prizepicks("standard", -137) == 0.5


def test_offered_demon_uses_plus_100():
    assert offered_prob_for_prizepicks("demon", 100) == pytest.approx(0.5)


def test_edge_pct():
    assert edge_pct(0.55, 0.5) == pytest.approx(5.0)
