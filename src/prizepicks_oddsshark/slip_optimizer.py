"""PrizePicks Power / Flex slip EV + Sharpe recommender (independence assumption).

Payout multipliers are approximate Player Pick values from PrizePicks help docs;
the live app can change them. Personal research only.

Sharpe-like score = EV / σ(profit) where profit = payout − 1 under independence.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Iterable, Literal, Sequence

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

# Guard tiny σ so Sharpe does not explode; treat below floor as unscorable (0).
SHARPE_SIGMA_FLOOR: float = 1e-9

RankMetric = Literal["ev", "sharpe"]


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
    sharpe: float = 0.0  # EV / σ(profit); 0 if σ≈0
    sigma: float = 0.0  # σ(profit)

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


def _sharpe_from_moments(ev: float, e_profit_sq: float) -> tuple[float, float]:
    """Return (sharpe, sigma) from E[profit]=ev and E[profit²]."""
    var = max(e_profit_sq - ev * ev, 0.0)
    sigma = math.sqrt(var)
    if sigma < SHARPE_SIGMA_FLOOR:
        return 0.0, sigma
    return ev / sigma, sigma


def power_ev(probs: Sequence[float]) -> SlipEV:
    n = len(probs)
    if n not in POWER_MULTIPLIERS:
        raise ValueError(f"Power not supported for n={n}")
    mult = POWER_MULTIPLIERS[n]
    p_all = 1.0
    for p in probs:
        p_all *= float(p)
    expected = p_all * mult
    ev = expected - 1.0
    # Two-point: hit → mult−1, miss → −1
    profit_hit = mult - 1.0
    e_sq = p_all * (profit_hit * profit_hit) + (1.0 - p_all) * 1.0
    sharpe, sigma = _sharpe_from_moments(ev, e_sq)
    return SlipEV(
        n=n,
        kind="power",
        label=f"{n} Power",
        ev=ev,
        expected_payout=expected,
        p_cash=p_all,
        p_max=p_all,
        multiplier_max=mult,
        sharpe=sharpe,
        sigma=sigma,
    )


def flex_ev(probs: Sequence[float]) -> SlipEV:
    n = len(probs)
    if n not in FLEX_PAYOUTS:
        raise ValueError(f"Flex not supported for n={n}")
    pay = FLEX_PAYOUTS[n]
    expected = 0.0
    p_cash = 0.0
    e_sq = 0.0
    for k in range(0, n + 1):
        pk = _prob_exactly_k_hits(probs, k)
        mult = float(pay.get(k, 0.0))
        expected += pk * mult
        if mult > 0:
            p_cash += pk
        profit = mult - 1.0
        e_sq += pk * (profit * profit)
    ev = expected - 1.0
    sharpe, sigma = _sharpe_from_moments(ev, e_sq)
    p_max = _prob_exactly_k_hits(probs, n)
    return SlipEV(
        n=n,
        kind="flex",
        label=f"{n} Flex",
        ev=ev,
        expected_payout=expected,
        p_cash=p_cash,
        p_max=p_max,
        multiplier_max=float(pay.get(n, 0.0)),
        sharpe=sharpe,
        sigma=sigma,
    )


def evaluate_slip(probs: Sequence[float], kind: str) -> SlipEV:
    kind = kind.lower().strip()
    if kind == "power":
        return power_ev(probs)
    if kind == "flex":
        return flex_ev(probs)
    raise ValueError(f"Unknown slip kind: {kind}")


def rank_slip_types(probs: Sequence[float], *, rank: RankMetric = "ev") -> list[SlipEV]:
    """Rank all slip types that match len(probs) by EV or Sharpe descending."""
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
    key = (lambda r: r.sharpe) if rank == "sharpe" else (lambda r: r.ev)
    results.sort(key=key, reverse=True)
    return results


def recommend_best(probs: Sequence[float], *, rank: RankMetric = "ev") -> SlipEV:
    ranked = rank_slip_types(probs, rank=rank)
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


# --- Auto-suggest from board edges (junk filter + combo search) ---

# Skip obvious bad DFS↔book matches (tunable). Documented in README.
JUNK_MAX_EDGE_PCT: float = 15.0
JUNK_MAX_ABS_LINE_DIFF: float = 5.0
DEFAULT_SUGGEST_POOL: int = 16
DEFAULT_SUGGEST_TOP: int = 6
BEST_BY_N_SIZES: tuple[int, ...] = (3, 4, 5, 6)


def is_junk_edge(edge: dict[str, Any]) -> bool:
    """True if the row lacks a usable fair_prob or looks like a bad match.

    Rules (OR):
    - fair_prob missing / not finite / not in (0, 1)
    - edge_pct > JUNK_MAX_EDGE_PCT (default 15)
    - |line_diff| > JUNK_MAX_ABS_LINE_DIFF (default 5)
    """
    try:
        fp = float(edge["fair_prob"]) if edge.get("fair_prob") is not None else float("nan")
    except (TypeError, ValueError):
        return True
    if not (0.0 < fp < 1.0):
        return True
    try:
        ep = float(edge.get("edge_pct") or 0.0)
    except (TypeError, ValueError):
        ep = 0.0
    if ep > JUNK_MAX_EDGE_PCT:
        return True
    try:
        ld = edge.get("line_diff")
        if ld is not None and abs(float(ld)) > JUNK_MAX_ABS_LINE_DIFF:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _edge_platform(edge: dict[str, Any]) -> str:
    return str(edge.get("platform") or "prizepicks").lower().strip()


def _edge_key(edge: dict[str, Any]) -> str:
    return "|".join(
        str(x)
        for x in (
            edge.get("platform") or "prizepicks",
            edge.get("event_id"),
            edge.get("player"),
            edge.get("market"),
            edge.get("side"),
            edge.get("pp_line"),
            edge.get("tier"),
        )
    )


def candidate_pool_from_edges(
    edges: Iterable[dict[str, Any]],
    *,
    platform: str | None = None,
    pool_size: int = DEFAULT_SUGGEST_POOL,
) -> list[dict[str, Any]]:
    """Top-K by edge_pct among non-junk edges with fair_prob (optional platform filter)."""
    plat = (platform or "").lower().strip() or None
    rows: list[dict[str, Any]] = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        if plat and plat != "both" and _edge_platform(e) != plat:
            continue
        if is_junk_edge(e):
            continue
        rows.append(e)
    rows.sort(key=lambda e: float(e.get("edge_pct") or 0), reverse=True)
    k = max(2, min(int(pool_size), 30))
    return rows[:k]


def _score_key(rank: RankMetric):
    if rank == "sharpe":
        return lambda r: float(r.get("sharpe") or 0.0)
    return lambda r: float(r.get("ev") or 0.0)


def _suggestion_row(
    picks: list[dict[str, Any]],
    probs: list[float],
    slip: SlipEV,
) -> dict[str, Any]:
    return {
        "label": slip.label,
        "ev": slip.ev,
        "sharpe": slip.sharpe,
        "sigma": slip.sigma,
        "expected_payout": slip.expected_payout,
        "p_cash": slip.p_cash,
        "p_max": slip.p_max,
        "n": slip.n,
        "kind": slip.kind,
        "picks": picks,
        "probs": probs,
        "keys": [_edge_key(p) for p in picks],
    }


def _diversify_top(scored: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in scored:
        if len(out) >= limit:
            break
        keys = set(s["keys"])
        too_similar = False
        for o in out:
            if len(o["keys"]) != len(s["keys"]):
                continue
            shared = sum(1 for k in o["keys"] if k in keys)
            if shared >= len(s["keys"]) - 1:
                too_similar = True
                break
        if too_similar:
            continue
        out.append(s)
    return out


def suggest_slips_from_edges(
    edges: Iterable[dict[str, Any]],
    *,
    platform: str | None = None,
    pool_size: int = DEFAULT_SUGGEST_POOL,
    top: int = DEFAULT_SUGGEST_TOP,
    min_n: int = 2,
    max_n: int = 6,
    diversify: bool = True,
    rank: RankMetric = "ev",
) -> dict[str, Any]:
    """Search Power/Flex combos of size 2–6 from a top-K candidate pool.

    Scores every (combo, Power|Flex) pair. Returns::

        {
          "ranked": [...],      # top suggestions by ``rank`` (ev|sharpe)
          "best_by_n": [...],   # best Power-or-Flex for n in 3,4,5,6 by ``rank``
          "rank": "ev"|"sharpe",
        }

    Each suggestion dict includes: label, ev, sharpe, expected_payout, p_cash, p_max,
    n, kind, picks, probs, keys.
    """
    if rank not in ("ev", "sharpe"):
        raise ValueError("rank must be 'ev' or 'sharpe'")

    pool = candidate_pool_from_edges(edges, platform=platform, pool_size=pool_size)
    empty = {"ranked": [], "best_by_n": [], "rank": rank}
    if len(pool) < min_n:
        return empty

    scored: list[dict[str, Any]] = []
    lo = max(2, min_n)
    hi = min(6, max_n, len(pool))
    for n in range(lo, hi + 1):
        for idxs in combinations(range(len(pool)), n):
            picks = [pool[i] for i in idxs]
            probs = [float(p["fair_prob"]) for p in picks]
            for sn, kind in SLIP_TYPES:
                if sn != n:
                    continue
                slip = evaluate_slip(probs, kind)
                scored.append(_suggestion_row(picks, probs, slip))

    key_fn = _score_key(rank)
    scored.sort(key=key_fn, reverse=True)

    limit = max(1, min(int(top), 20))
    ranked = _diversify_top(scored, limit) if diversify else scored[:limit]

    # Best-by-size: absolute best Power-or-Flex for each n in 3..6 (no diversify).
    best_by_n: list[dict[str, Any]] = []
    for n in BEST_BY_N_SIZES:
        candidates = [s for s in scored if s["n"] == n]
        if not candidates:
            continue
        best_by_n.append(max(candidates, key=key_fn))

    return {"ranked": ranked, "best_by_n": best_by_n, "rank": rank}
