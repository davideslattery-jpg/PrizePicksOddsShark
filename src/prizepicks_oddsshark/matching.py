"""Normalize player/market keys and match PrizePicks props to book props."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Literal

Tier = Literal["standard", "goblin", "demon"]

# Sports supported by the CLI / board (core + optional college).
SUPPORTED_SPORTS: tuple[str, ...] = (
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "icehockey_nhl",
    "americanfootball_ncaaf",
    "basketball_ncaab",
)

# "all" expands to this set (college included; empty seasons skip gracefully).
ALL_SPORTS: tuple[str, ...] = SUPPORTED_SPORTS

# Common market aliases → canonical Odds API keys (base, without _alternate)
MARKET_ALIASES: dict[str, str] = {
    "player_points": "player_points",
    "points": "player_points",
    "pts": "player_points",
    "player_rebounds": "player_rebounds",
    "rebounds": "player_rebounds",
    "reb": "player_rebounds",
    "player_assists": "player_assists",
    "assists": "player_assists",
    "ast": "player_assists",
    "player_threes": "player_threes",
    "threes": "player_threes",
    "3pm": "player_threes",
    "player_blocks": "player_blocks",
    "blocks": "player_blocks",
    "player_steals": "player_steals",
    "steals": "player_steals",
    "player_points_rebounds_assists": "player_points_rebounds_assists",
    "pra": "player_points_rebounds_assists",
    "player_points_rebounds": "player_points_rebounds",
    "pr": "player_points_rebounds",
    "player_points_assists": "player_points_assists",
    "pa": "player_points_assists",
    "player_rebounds_assists": "player_rebounds_assists",
    "ra": "player_rebounds_assists",
    "player_pass_yds": "player_pass_yds",
    "player_pass_tds": "player_pass_tds",
    "player_pass_completions": "player_pass_completions",
    "player_pass_attempts": "player_pass_attempts",
    "player_pass_interceptions": "player_pass_interceptions",
    "player_rush_yds": "player_rush_yds",
    "player_rush_tds": "player_rush_tds",
    "player_rush_attempts": "player_rush_attempts",
    "player_reception_yds": "player_reception_yds",
    "player_reception_tds": "player_reception_tds",
    "player_receptions": "player_receptions",
    "player_anytime_td": "player_anytime_td",
    # MLB
    "batter_hits": "batter_hits",
    "hits": "batter_hits",
    "batter_total_bases": "batter_total_bases",
    "total_bases": "batter_total_bases",
    "pitcher_strikeouts": "pitcher_strikeouts",
    "strikeouts": "pitcher_strikeouts",
    "batter_home_runs": "batter_home_runs",
    "batter_rbis": "batter_rbis",
    "batter_runs_scored": "batter_runs_scored",
    "batter_hits_runs_rbis": "batter_hits_runs_rbis",
    # NHL
    "player_goals": "player_goals",
    "goals": "player_goals",
    "player_shots_on_goal": "player_shots_on_goal",
    "shots": "player_shots_on_goal",
    "player_power_play_points": "player_power_play_points",
}

DEFAULT_MARKETS_NBA = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_points_rebounds_assists",
]

DEFAULT_MARKETS_NFL = [
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_yds",
    "player_rush_tds",
    "player_reception_yds",
    "player_receptions",
]

DEFAULT_MARKETS_MLB = [
    "batter_hits",
    "batter_total_bases",
    "pitcher_strikeouts",
    "batter_home_runs",
    "batter_hits_runs_rbis",
]

DEFAULT_MARKETS_NHL = [
    "player_goals",
    "player_shots_on_goal",
    "player_points",
    "player_assists",
]

DEFAULT_MARKETS_NCAAB = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
]

DEFAULT_MARKETS_NCAAF = [
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
]

_SPORT_MARKETS: dict[str, list[str]] = {
    "basketball_nba": DEFAULT_MARKETS_NBA,
    "americanfootball_nfl": DEFAULT_MARKETS_NFL,
    "baseball_mlb": DEFAULT_MARKETS_MLB,
    "icehockey_nhl": DEFAULT_MARKETS_NHL,
    "basketball_ncaab": DEFAULT_MARKETS_NCAAB,
    "americanfootball_ncaaf": DEFAULT_MARKETS_NCAAF,
}


def default_markets_for_sport(sport: str) -> list[str]:
    """Return sensible Odds API market keys for a sport (copy)."""
    return list(_SPORT_MARKETS.get(sport, DEFAULT_MARKETS_NBA))


def parse_sport_arg(sport: str) -> list[str]:
    """Parse --sport value: single key, comma list, or 'all'.

    Raises ValueError for unknown keys.
    """
    raw = (sport or "").strip()
    if not raw:
        raise ValueError("sport is empty")
    if raw.lower() == "all":
        return list(ALL_SPORTS)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("sport is empty")
    unknown = [p for p in parts if p not in SUPPORTED_SPORTS]
    if unknown:
        raise ValueError(
            f"Unsupported sport(s): {', '.join(unknown)}. "
            f"Use: {', '.join(SUPPORTED_SPORTS)}, or 'all'"
        )
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace for matching."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = text.replace(".", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Drop common suffixes / Jr / III noise for loose match
    parts = text.split()
    drop = {"jr", "sr", "ii", "iii", "iv", "v"}
    parts = [p for p in parts if p not in drop]
    return " ".join(parts)


def canonical_market(market_key: str) -> str:
    """Strip `_alternate` and map aliases to a base market key."""
    key = (market_key or "").strip().lower()
    is_alt = key.endswith("_alternate")
    base = key[: -len("_alternate")] if is_alt else key
    return MARKET_ALIASES.get(base, base)


def is_alternate_market(market_key: str) -> bool:
    return (market_key or "").lower().endswith("_alternate")


def classify_prizepicks_tier(market_key: str, price: float | int | None) -> Tier:
    """Classify PrizePicks outcome tier from market + American price.

    Per The Odds API: demons/goblins live in `_alternate` markets;
    demons ≈ +100, goblins ≈ default odds. Main markets ≈ standard lines.
    """
    if not is_alternate_market(market_key):
        return "standard"
    if price is not None and int(price) == 100:
        return "demon"
    return "goblin"


@dataclass(frozen=True)
class PropLeg:
    event_id: str
    sport_key: str
    commence_time: str
    home_team: str
    away_team: str
    bookmaker: str
    market_key: str
    base_market: str
    player: str
    player_norm: str
    side: str  # Over / Under
    point: float
    price: float | None
    tier: Tier | None = None  # only for prizepicks


def extract_props_from_event(
    event: dict[str, Any],
    *,
    bookmaker_keys: Iterable[str],
    market_filter: Iterable[str] | None = None,
) -> list[PropLeg]:
    """Flatten event odds JSON into PropLeg rows for selected bookmakers."""
    allowed_books = {b.lower() for b in bookmaker_keys}
    allowed_markets: set[str] | None = None
    if market_filter is not None:
        allowed_markets = {canonical_market(m) for m in market_filter}

    legs: list[PropLeg] = []
    event_id = str(event.get("id", ""))
    sport_key = str(event.get("sport_key", ""))
    commence = str(event.get("commence_time", ""))
    home = str(event.get("home_team", ""))
    away = str(event.get("away_team", ""))

    for book in event.get("bookmakers") or []:
        bkey = str(book.get("key", "")).lower()
        if bkey not in allowed_books:
            continue
        for market in book.get("markets") or []:
            mkey = str(market.get("key", ""))
            base = canonical_market(mkey)
            if allowed_markets is not None and base not in allowed_markets:
                continue
            for outcome in market.get("outcomes") or []:
                side = str(outcome.get("name") or "")
                # Player props: name is Over/Under, description is player
                if side not in ("Over", "Under"):
                    # Skip non O/U (e.g. anytime TD Yes)
                    continue
                point = outcome.get("point")
                if point is None:
                    continue
                price = outcome.get("price")
                tier: Tier | None = None
                if bkey == "prizepicks":
                    tier = classify_prizepicks_tier(mkey, price)
                legs.append(
                    PropLeg(
                        event_id=event_id,
                        sport_key=sport_key,
                        commence_time=commence,
                        home_team=home,
                        away_team=away,
                        bookmaker=bkey,
                        market_key=mkey,
                        base_market=base,
                        player=str(outcome.get("description") or ""),
                        player_norm=normalize_name(str(outcome.get("description") or "")),
                        side=side,
                        point=float(point),
                        price=float(price) if price is not None else None,
                        tier=tier,
                    )
                )
    return legs


def match_key(player_norm: str, base_market: str, side: str) -> tuple[str, str, str]:
    return (player_norm, base_market, side)


def index_book_props(legs: Iterable[PropLeg]) -> dict[tuple[str, str, str], list[PropLeg]]:
    """Index sportsbook legs by (player, market, side); keep all lines for nearest-line match."""
    idx: dict[tuple[str, str, str], list[PropLeg]] = {}
    for leg in legs:
        k = match_key(leg.player_norm, leg.base_market, leg.side)
        idx.setdefault(k, []).append(leg)
    return idx


def nearest_book_leg(candidates: list[PropLeg], pp_point: float) -> PropLeg | None:
    if not candidates:
        return None
    return min(candidates, key=lambda c: (abs(c.point - pp_point), c.point))
