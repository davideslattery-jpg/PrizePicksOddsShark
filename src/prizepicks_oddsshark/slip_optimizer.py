"""PrizePicks Power / Flex slip EV recommender (independence assumption).

Payout multipliers are approximate Player Pick values from PrizePicks help docs;
the live app can change them. Personal research only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Iterable, Sequence

# Approximate Power multipliers (all must hit) for n picks → payout multiple of stake.
POWER_MULTIPLIERS: dict[int, float] = {
    2: 3.0,
    3: 6.0,
    4: 10.0,
    5: 20.0,
    6: 37.5,
}

# Flex: hit_count → payout multiple. Missing keys pay 0.
FLEX_PAYOUTS: dict[int, dict[int, float]] = {
    2: {2: 2.0, 1: 0.5},
    3: {3: 3.0, 2: 1.0},
    4: {4: 6.0, 3: 1.5},
    5: {5: 10.0, 4: 2.0, 3: 0.4},
    6: {6: 25.0, 5: 2.0, 4: 0.4},
}

# Slip types shown on PrizePicks (n, kind) — order matches product UI roughly.
SLIP_TYPES: tuple[tuple[int, str], ...] = (
    (2, "power"),
    (3, "power"),
    (3, "flex"),
    (4, "power"),
    (4, "flex"),
    (5, "flex"),
    (5, "power"),
    (6, "flex"),
    (6, "power"),
)


@dataclass(frozen=True)
class SlipEV:
    n: int
    kind: str  # power | flex
    label: str
    ev: float  # expected profit per $1 stake (E[payout] - 1)
    expected_payout: float
    p_cash: float  # any paying tier
    p_max: float  # max tier (all hit for power; n/n for flex)
    multiplier_max: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _prob_exactly_k_hits(probs: Sequence[float], k: int) -> float:
    """Exact P(exactly k hits) under independence via subset enumeration (n≤6)."""
    n = len(probs)
    if k < 0 or k > n:
        return 0.0
    total = 0.0
    for idxs in combinations(range(n), k):
        hit = set(idxs)
        p = 1.0
        for i, pi in enumerate(probs):
            p *= pi if i in hit else (1.0 - pi)
        total += p
    return total


def power_ev(probs: Sequence[float]) -> SlipEV:
    n = len(probs)
    if n not in POWER_MULTIPLIERS:
        raise ValueError(f"Power not supported for n={n}")
    mult = POWER_MULTIPLIERS[n]
    p_all = 1.0
    for p in probs:
        p_all *= float(p)
    expected = p_all * mult
    return SlipEV(
        n=n,
        kind="power",
        label=f"{n} Power",
        ev=expected - 1.0,
        expected_payout=expected,
        p_cash=p_all,
        p_max=p_all,
        multiplier_max=mult,
    )


def flex_ev(probs: Sequence[float]) -> SlipEV:
    n = len(probs)
    if n not in FLEX_PAYOUTS:
        raise ValueError(f"Flex not supported for n={n}")
    pay = FLEX_PAYOUTS[n]
    expected = 0.0
    p_cash = 0.0
    for k, mult in pay.items():
        pk = _prob_exactly_k_hits(probs, k)
        expected += pk * mult
        if mult > 0:
            p_cash += pk
    p_max = _prob_exactly_k_hits(probs, n)
    return SlipEV(
        n=n,
        kind="flex",
        label=f"{n} Flex",
        ev=expected - 1.0,
        expected_payout=expected,
        p_cash=p_cash,
        p_max=p_max,
        multiplier_max=float(pay.get(n, 0.0)),
    )


def evaluate_slip(probs: Sequence[float], kind: str) -> SlipEV:
    kind = kind.lower().strip()
    if kind == "power":
        return power_ev(probs)
    if kind == "flex":
        return flex_ev(probs)
    raise ValueError(f"Unknown slip kind: {kind}")


def rank_slip_types(probs: Sequence[float]) -> list[SlipEV]:
    """Rank all slip types that match len(probs) by EV descending."""
    n = len(probs)
    if n < 2 or n > 6:
        raise ValueError("Need between 2 and 6 pick probabilities")
    cleaned = [float(p) for p in probs]
    if any(p < 0.0 or p > 1.0 for p in cleaned):
        raise ValueError("Probabilities must be in [0, 1]")
    results: list[SlipEV] = []
    for sn, kind in SLIP_TYPES:
        if sn != n:
            continue
        results.append(evaluate_slip(cleaned, kind))
    results.sort(key=lambda r: r.ev, reverse=True)
    return results


def recommend_best(probs: Sequence[float]) -> SlipEV:
    ranked = rank_slip_types(probs)
    if not ranked:
        raise ValueError("No slip types for this pick count")
    return ranked[0]


def probs_from_board_edges(
    edges: Iterable[dict[str, Any]],
    *,
    top: int = 4,
    prob_key: str = "fair_prob",
) -> list[float]:
    """Take top-N edges by edge_pct and return their book/fair probs."""
    rows = [e for e in edges if e.get(prob_key) is not None]
    rows.sort(key=lambda e: float(e.get("edge_pct") or 0), reverse=True)
    selected = rows[:top]
    if len(selected) < 2:
        raise ValueError("Need at least 2 edges with probabilities")
    if len(selected) > 6:
        selected = selected[:6]
    return [float(e[prob_key]) for e in selected]
