"""Match PrizePicks legs to book fair odds and rank by edge."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from prizepicks_oddsshark.matching import (
    extract_props_from_event,
    index_book_props,
    nearest_book_leg,
)
from prizepicks_oddsshark.probability import (
    edge_pct,
    fair_probs_from_american,
    line_adjusted_prob,
    offered_prob_for_prizepicks,
)


@dataclass
class RankedEdge:
    player: str
    market: str
    side: str
    pp_line: float
    book_line: float
    line_diff: float
    tier: str
    pp_price: float | None
    book_price_over: float | None
    book_price_under: float | None
    fair_prob: float
    offered_prob: float
    edge_pct: float
    book: str
    event_id: str
    commence_time: str
    matchup: str
    adjusted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rank_edges(
    events: list[dict[str, Any]],
    *,
    book: str = "fanduel",
    markets: list[str] | None = None,
    min_edge: float = 2.0,
) -> list[RankedEdge]:
    """Build ranked edges from event-odds payloads."""
    results: list[RankedEdge] = []

    for event in events:
        pp_legs = extract_props_from_event(
            event, bookmaker_keys=["prizepicks"], market_filter=markets
        )
        book_legs = extract_props_from_event(
            event, bookmaker_keys=[book], market_filter=markets
        )
        book_idx = index_book_props(book_legs)

        for pp in pp_legs:
            if not pp.player_norm:
                continue
            candidates = book_idx.get((pp.player_norm, pp.base_market, pp.side), [])
            book_same = nearest_book_leg(candidates, pp.point)
            if book_same is None or book_same.price is None:
                continue

            opp_side = "Under" if pp.side == "Over" else "Over"
            opp_cands = book_idx.get((pp.player_norm, pp.base_market, opp_side), [])
            same_line = [c for c in opp_cands if c.point == book_same.point]
            book_opp = same_line[0] if same_line else nearest_book_leg(opp_cands, book_same.point)
            if book_opp is None or book_opp.price is None:
                continue

            if pp.side == "Over":
                over_price, under_price = book_same.price, book_opp.price
            else:
                over_price, under_price = book_opp.price, book_same.price

            fair_over, _fair_under = fair_probs_from_american(over_price, under_price)
            adjusted = abs(pp.point - book_same.point) > 1e-9
            if adjusted:
                fair = line_adjusted_prob(
                    fair_over,
                    book_line=book_same.point,
                    target_line=pp.point,
                    side=pp.side,  # type: ignore[arg-type]
                )
            else:
                fair = fair_over if pp.side == "Over" else (1.0 - fair_over)

            tier = pp.tier or "standard"
            offered = offered_prob_for_prizepicks(tier, pp.price)
            edge = edge_pct(fair, offered)
            if edge < min_edge:
                continue

            results.append(
                RankedEdge(
                    player=pp.player,
                    market=pp.base_market,
                    side=pp.side,
                    pp_line=pp.point,
                    book_line=book_same.point,
                    line_diff=round(pp.point - book_same.point, 3),
                    tier=tier,
                    pp_price=pp.price,
                    book_price_over=over_price,
                    book_price_under=under_price,
                    fair_prob=round(fair, 4),
                    offered_prob=round(offered, 4),
                    edge_pct=round(edge, 2),
                    book=book,
                    event_id=pp.event_id,
                    commence_time=pp.commence_time,
                    matchup=f"{pp.away_team} @ {pp.home_team}",
                    adjusted=adjusted,
                )
            )

    results.sort(key=lambda r: r.edge_pct, reverse=True)
    return results
