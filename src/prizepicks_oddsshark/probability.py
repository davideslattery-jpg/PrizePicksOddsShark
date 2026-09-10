"""American odds conversion, multiplicative de-vig, line adjustment, edge."""

from __future__ import annotations

import math
from typing import Literal

Side = Literal["Over", "Under"]


def american_to_implied(odds: float | int) -> float:
    """Convert American odds to raw implied probability (includes vig).

    Negative: |o| / (|o| + 100)
    Positive: 100 / (o + 100)
    """
    o = float(odds)
    if o == 0:
        raise ValueError("American odds cannot be 0")
    if o < 0:
        return abs(o) / (abs(o) + 100.0)
    return 100.0 / (o + 100.0)


def implied_to_american(p: float) -> float:
    """Approximate American odds from a fair probability in (0, 1)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"Probability must be in (0,1), got {p}")
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def multiplicative_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Two-way multiplicative de-vig so fair probabilities sum to 1."""
    total = prob_a + prob_b
    if total <= 0:
        raise ValueError("Implied probabilities must be positive")
    return prob_a / total, prob_b / total


def fair_probs_from_american(odds_a: float | int, odds_b: float | int) -> tuple[float, float]:
    """Raw implied → multiplicative de-vig for a two-way market."""
    return multiplicative_devig(american_to_implied(odds_a), american_to_implied(odds_b))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Approximate inverse CDF of standard normal (Acklam / Beasley-Springer style)."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be in (0,1), got {p}")
    # Coefficients for rational approximation
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577459334453e02,
        -3.066479806614736e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163459698733e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def line_adjusted_prob(
    fair_over_at_book: float,
    book_line: float,
    target_line: float,
    *,
    side: Side = "Over",
    sigma_frac: float = 0.15,
    sigma_floor: float = 1.0,
) -> float:
    """Adjust fair Over/Under probability when PrizePicks line ≠ book line.

    Model: latent stat ~ Normal(mu, sigma). At the book line we know P(Over).
    sigma = max(|book_line| * sigma_frac, sigma_floor).

    z_book = Φ^{-1}(1 - P_over)  # standardized threshold for Over at book_line
    z_target = z_book + (target_line - book_line) / sigma
    P_over(target) = 1 - Φ(z_target)

    See README "Line mismatch adjustment".
    """
    p_over = float(fair_over_at_book)
    p_over = min(max(p_over, 1e-6), 1.0 - 1e-6)
    sigma = max(abs(float(book_line)) * sigma_frac, sigma_floor)
    z_book = _norm_ppf(1.0 - p_over)
    z_target = z_book + (float(target_line) - float(book_line)) / sigma
    p_over_target = 1.0 - _norm_cdf(z_target)
    p_over_target = min(max(p_over_target, 1e-6), 1.0 - 1e-6)
    if side == "Over":
        return p_over_target
    return 1.0 - p_over_target


def offered_prob_for_prizepicks(
    tier: Literal["standard", "goblin", "demon"],
    american_odds: float | int | None,
) -> float:
    """PrizePicks offered implied probability used for edge.

    - standard: even-money proxy 0.5 (DFS entry pricing, not true American odds)
    - demon / goblin: use Odds API American price when present; demon ≈ +100
    """
    if tier == "standard":
        return 0.5
    if american_odds is None:
        # Fallback: demon even money, goblin slightly favored (approx default)
        return 0.5 if tier == "demon" else american_to_implied(-137)
    return american_to_implied(american_odds)


def edge_pct(fair_prob: float, offered_prob: float) -> float:
    """Absolute edge in percentage points: (fair - offered) * 100."""
    return (fair_prob - offered_prob) * 100.0
