"""OddsPapi (api.oddspapi.io) client — maps responses into The Odds API event shape.

Auth: apiKey query param. Free-tier friendly: disk cache, tournament filters,
prizepicks/underdog + fanduel bookmakers, request pacing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://api.oddspapi.io"
DEFAULT_TTL = 480  # ~8 min for fixtures/odds
MARKETS_TTL = 7 * 24 * 3600  # markets catalog changes rarely
REQUEST_GAP_SEC = 1.05  # respect ~1s endpoint cooldown


class OddsPapiError(RuntimeError):
    pass


@dataclass(frozen=True)
class SportConfig:
    sport_id: int
    tournament_ids: tuple[int, ...]
    label: str


# Verified via GET /v4/tournaments (NBA=132, NFL=31, NCAAF regular=27653).
SPORT_CONFIG: dict[str, SportConfig] = {
    "basketball_nba": SportConfig(11, (132, 2382, 40401), "NBA"),
    "americanfootball_nfl": SportConfig(14, (31,), "NFL"),
    "americanfootball_ncaaf": SportConfig(14, (27653, 850, 27625), "NCAAF"),
    "basketball_ncaab": SportConfig(11, (648, 29630, 28370), "NCAAB"),
}

# Ordered specific → general. First match wins.
_MARKET_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"points\s*\+\s*assists\s*\+\s*rebounds|pra\b", re.I), "player_points_rebounds_assists"),
    (re.compile(r"points\s*\+\s*rebounds\b", re.I), "player_points_rebounds"),
    (re.compile(r"points\s*\+\s*assists\b", re.I), "player_points_assists"),
    (re.compile(r"assists\s*\+\s*rebounds\b", re.I), "player_rebounds_assists"),
    (re.compile(r"steals\s*\+\s*blocks", re.I), "player_steals"),  # closest lean alias
    (re.compile(r"3\s*point|three\s*point", re.I), "player_threes"),
    (re.compile(r"\brebounds\b", re.I), "player_rebounds"),
    (re.compile(r"\bassists\b", re.I), "player_assists"),
    (re.compile(r"\bblocks\b", re.I), "player_blocks"),
    (re.compile(r"\bsteals\b", re.I), "player_steals"),
    (re.compile(r"\bpoints\b", re.I), "player_points"),
    (re.compile(r"td\s*passes|pass(ing)?\s*td|touchdown\s*passes", re.I), "player_pass_tds"),
    (re.compile(r"pass(ing)?\s*yards?", re.I), "player_pass_yds"),
    (re.compile(r"pass(ing)?\s*completions?", re.I), "player_pass_completions"),
    (re.compile(r"pass(ing)?\s*attempts?", re.I), "player_pass_attempts"),
    (re.compile(r"rush(ing)?\s*td|rush\s*touchdown", re.I), "player_rush_tds"),
    (re.compile(r"rush(ing)?\s*yards?", re.I), "player_rush_yds"),
    (re.compile(r"rush(ing)?\s*attempts?", re.I), "player_rush_attempts"),
    (re.compile(r"receiv(ing)?\s*yards?", re.I), "player_reception_yds"),
    (re.compile(r"receiv(ing)?\s*td|reception\s*td", re.I), "player_reception_tds"),
    (re.compile(r"\breceptions?\b", re.I), "player_receptions"),
    (re.compile(r"player\s*td\b|anytime\s*td|to\s*score\s*td", re.I), "player_anytime_td"),
]


def map_market_name(market_name: str) -> str | None:
    """Map OddsPapi marketName → canonical Odds API-style market key, or None to skip."""
    name = (market_name or "").strip()
    if not name:
        return None
    low = name.lower()
    # Skip period / specialty lines we don't rank
    if any(
        x in low
        for x in (
            "first quarter",
            "1st quarter",
            "second quarter",
            "2nd quarter",
            "third quarter",
            "3rd quarter",
            "fourth quarter",
            "1st half",
            "first half",
            "2nd half",
            "second half",
            "longest",
            "to score second",
            "to score third",
        )
    ):
        return None
    for pat, key in _MARKET_RULES:
        if pat.search(name):
            return key
    return None


def normalize_player_name(name: str) -> str:
    """Convert 'Last, First' → 'First Last'; leave 'First Last' alone."""
    raw = (name or "").strip()
    if not raw:
        return ""
    if "," in raw:
        last, first = raw.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return raw


def _parse_american(price: Any) -> float | None:
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    s = str(price).strip().replace("+", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


class OddsPapiClient:
    """Live OddsPapi client producing The Odds API-shaped event dicts for ranker."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache_dir: str | Path | None = None,
        cache_ttl: int | None = None,
        timeout: float = 45.0,
        fixtures_dir: str | Path | None = None,
        demo: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv("ODDSPAPI_API_KEY")
        self.cache_ttl = int(cache_ttl or os.getenv("ODDS_CACHE_TTL") or DEFAULT_TTL)
        self.cache_dir = Path(cache_dir or os.getenv("ODDS_CACHE_DIR") or ".odds_cache")
        self.timeout = timeout
        self.demo = demo
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else _default_fixtures_dir()
        self.last_headers: dict[str, str] = {}
        self.request_count = 0
        self._last_request_at = 0.0
        self._markets_by_id: dict[int, dict[str, Any]] | None = None
        self._outcome_name: dict[int, str] = {}
        if not demo:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --- cache ---

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:40]
        return self.cache_dir / f"op_{digest}.json"

    def _read_cache(self, key: str, ttl: int | None = None) -> Any | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        ts = payload.get("_cached_at", 0)
        if time.time() - ts > (ttl if ttl is not None else self.cache_ttl):
            return None
        return payload.get("data")

    def _write_cache(self, key: str, data: Any) -> None:
        path = self._cache_path(key)
        blob = {"_cached_at": time.time(), "data": data}
        path.write_text(json.dumps(blob), encoding="utf-8")

    def _pace(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < REQUEST_GAP_SEC:
            time.sleep(REQUEST_GAP_SEC - elapsed)

    def _get(self, path: str, params: dict[str, Any], *, ttl: int | None = None) -> Any:
        if self.demo:
            raise OddsPapiError("Live HTTP disabled in demo mode")
        if not self.api_key:
            raise OddsPapiError(
                "ODDSPAPI_API_KEY is not set. Copy .env.example to .env or pass --demo."
            )
        # Exclude apiKey from cache key
        cache_key = path + "?" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "apiKey"
        )
        cached = self._read_cache(cache_key, ttl=ttl)
        if cached is not None:
            return cached

        q = dict(params)
        q["apiKey"] = self.api_key
        url = f"{BASE_URL}{path}"
        last_err: Exception | None = None
        with httpx.Client(timeout=self.timeout) as client:
            for attempt in range(5):
                self._pace()
                resp = client.get(url, params=q)
                self._last_request_at = time.time()
                self.request_count += 1
                self.last_headers = {
                    "x-requests-used": str(self.request_count),
                    "x-requests-remaining": "?",
                }
                for hk, hv in resp.headers.items():
                    low = hk.lower()
                    if low.startswith("x-") and "key" not in low and "auth" not in low:
                        self.last_headers[low] = hv
                if resp.status_code == 401:
                    raise OddsPapiError("Unauthorized — check ODDSPAPI_API_KEY")
                if resp.status_code == 429:
                    last_err = OddsPapiError("Rate limited (429). Back off and retry.")
                    time.sleep(1.2 + attempt * 0.8)
                    continue
                if resp.status_code == 404:
                    # OddsPapi uses 404 for empty fixture filters
                    try:
                        body = resp.json()
                    except Exception:
                        body = {}
                    code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
                    if code in ("FIXTURE_NOT_FOUND", None):
                        data: Any = []
                        self._write_cache(cache_key, data)
                        return data
                    raise OddsPapiError(f"API error 404: {resp.text[:300]}")
                if resp.status_code >= 400:
                    raise OddsPapiError(f"API error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                self._write_cache(cache_key, data)
                return data
        raise last_err or OddsPapiError("Request failed after retries")

    # --- markets catalog ---

    def load_markets(self, *, force: bool = False) -> dict[int, dict[str, Any]]:
        if self._markets_by_id is not None and not force:
            return self._markets_by_id
        if self.demo:
            demo_path = self.fixtures_dir / "oddspapi" / "nfl_sample.json"
            payload = _load_json(demo_path)
            markets = payload.get("markets") or []
        else:
            markets = self._get("/v4/markets", {"language": "en"}, ttl=MARKETS_TTL)
            if not isinstance(markets, list):
                raise OddsPapiError("Unexpected /v4/markets response")
        by_id: dict[int, dict[str, Any]] = {}
        outcome_names: dict[int, str] = {}
        for m in markets:
            try:
                mid = int(m["marketId"])
            except (KeyError, TypeError, ValueError):
                continue
            by_id[mid] = m
            for o in m.get("outcomes") or []:
                try:
                    oid = int(o["outcomeId"])
                except (KeyError, TypeError, ValueError):
                    continue
                outcome_names[oid] = str(o.get("outcomeName") or "")
        self._markets_by_id = by_id
        self._outcome_name = outcome_names
        return by_id

    def _ensure_markets(self) -> None:
        self.load_markets()

    # --- fixtures / odds ---

    def list_fixtures(
        self,
        sport: str,
        *,
        team: str | None = None,
        days: int = 7,
        bookmakers: str = "fanduel",
    ) -> list[dict[str, Any]]:
        if self.demo:
            demo_path = self.fixtures_dir / "oddspapi" / "nfl_sample.json"
            payload = _load_json(demo_path)
            fixtures = list(payload.get("fixtures") or [])
            if sport != "americanfootball_nfl":
                return []
            return fixtures

        cfg = SPORT_CONFIG.get(sport)
        if not cfg:
            return []

        now = datetime.now(timezone.utc)
        # Keep window ≤ 9 days (API: tournamentId range under 10 days)
        days = max(1, min(int(days), 9))
        frm = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        to = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for tid in cfg.tournament_ids:
            try:
                data = self._get(
                    "/v4/fixtures",
                    {
                        "tournamentId": tid,
                        "from": frm,
                        "to": to,
                        "hasOdds": "true",
                        "bookmakers": bookmakers,
                        "statusId": 0,
                    },
                )
            except OddsPapiError:
                continue
            if not isinstance(data, list):
                continue
            for fx in data:
                fid = str(fx.get("fixtureId") or "")
                if not fid or fid in seen:
                    continue
                seen.add(fid)
                out.append(fx)

        out.sort(key=lambda f: str(f.get("startTime") or ""))
        if team:
            needle = team.strip().lower()
            out = [
                fx
                for fx in out
                if needle in str(fx.get("participant1Name") or "").lower()
                or needle in str(fx.get("participant2Name") or "").lower()
                or needle in str(fx.get("participant1ShortName") or "").lower()
                or needle in str(fx.get("participant2ShortName") or "").lower()
            ]
        return out

    def fixture_odds(
        self,
        fixture_id: str,
        *,
        bookmakers: str = "prizepicks,fanduel",
    ) -> dict[str, Any]:
        if self.demo:
            demo_path = self.fixtures_dir / "oddspapi" / "nfl_sample.json"
            payload = _load_json(demo_path)
            return payload["odds"]
        return self._get(
            "/v4/odds",
            {
                "fixtureId": fixture_id,
                "bookmakers": bookmakers,
                "oddsFormat": "american",
                "verbosity": 3,
            },
        )

    def odds_to_event(
        self,
        odds: dict[str, Any],
        *,
        sport: str,
        market_filter: list[str] | None = None,
        bookmakers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Convert OddsPapi /v4/odds payload → The Odds API event dict."""
        self._ensure_markets()
        allowed_markets = {m.lower() for m in market_filter} if market_filter else None
        allowed_books = {b.lower() for b in (bookmakers or ["prizepicks", "fanduel"])}

        # OddsPapi: participant1 typically away, participant2 home (US listings).
        away = str(odds.get("participant1Name") or "")
        home = str(odds.get("participant2Name") or "")
        event: dict[str, Any] = {
            "id": str(odds.get("fixtureId") or ""),
            "sport_key": sport,
            "sport_title": SPORT_CONFIG.get(sport, SportConfig(0, (), sport)).label,
            "commence_time": _iso_z(odds.get("startTime")),
            "home_team": home,
            "away_team": away,
            "bookmakers": [],
        }

        bookmaker_odds = odds.get("bookmakerOdds") or {}
        for book_key, book_data in bookmaker_odds.items():
            bkey = str(book_key).lower()
            if bkey not in allowed_books:
                continue
            if not isinstance(book_data, dict):
                continue
            # Group outcomes by canonical market key
            grouped: dict[str, list[dict[str, Any]]] = {}
            for mid_str, mdata in (book_data.get("markets") or {}).items():
                try:
                    mid = int(mid_str)
                except (TypeError, ValueError):
                    continue
                meta = (self._markets_by_id or {}).get(mid) or {}
                mname = str(meta.get("marketName") or "")
                # Prefer playerProp flag when catalog knows; else infer from playerName
                is_prop = bool(meta.get("playerProp"))
                point = meta.get("handicap")
                canon = map_market_name(mname) if mname else None
                if canon is None and not mname:
                    continue
                if canon is None:
                    continue
                if allowed_markets is not None and canon not in allowed_markets:
                    continue
                if point is None:
                    continue
                try:
                    point_f = float(point)
                except (TypeError, ValueError):
                    continue

                for oid_str, odata in (mdata.get("outcomes") or {}).items():
                    try:
                        oid = int(oid_str)
                    except (TypeError, ValueError):
                        continue
                    side = self._outcome_name.get(oid) or ""
                    if side not in ("Over", "Under"):
                        # Fallback: even/odd marketId convention often Over=mid, Under=mid+1
                        continue
                    for _pid, pdata in (odata.get("players") or {}).items():
                        if not isinstance(pdata, dict):
                            continue
                        pname = pdata.get("playerName")
                        if not pname:
                            if is_prop:
                                continue
                            continue
                        if pdata.get("active") is False:
                            continue
                        price = _parse_american(pdata.get("priceAmerican"))
                        if price is None and pdata.get("price") is not None:
                            # decimal → skip rather than guess american
                            continue
                        player = normalize_player_name(str(pname))
                        grouped.setdefault(canon, []).append(
                            {
                                "name": side,
                                "description": player,
                                "price": price,
                                "point": point_f,
                            }
                        )

            markets_out = [
                {"key": mkey, "last_update": _iso_z(odds.get("updatedAt")), "outcomes": outs}
                for mkey, outs in grouped.items()
                if outs
            ]
            if markets_out:
                event["bookmakers"].append(
                    {"key": bkey, "title": bkey.title(), "markets": markets_out}
                )
        return event

    def fetch_prop_events(
        self,
        sport: str,
        markets: list[str],
        *,
        book: str = "fanduel",
        max_events: int = 8,
        include_alternates: bool = True,  # noqa: ARG002 — OddsPapi has no *_alternate keys
        team: str | None = None,
        dfs: str | list[str] | None = "both",
    ) -> list[dict[str, Any]]:
        """List fixtures then pull DFS+book odds, mapped to Odds API event shape."""
        from prizepicks_oddsshark.ranker import parse_dfs_arg

        void = include_alternates  # retained for OddsClient interface parity
        del void

        if sport not in SPORT_CONFIG and not self.demo:
            return []

        dfs_keys = parse_dfs_arg(dfs)
        # Discover fixtures by fair-book hasOdds (DFS coverage is often sparse)
        fixtures = self.list_fixtures(sport, team=team, bookmakers=book)
        book_list = list(dict.fromkeys([*dfs_keys, book if book != "prizepicks" else "fanduel"]))
        books = ",".join(book_list)
        if self.demo:
            odds = self.fixture_odds("demo", bookmakers=books)
            self._ensure_markets()
            return [
                self.odds_to_event(
                    odds, sport=sport, market_filter=markets, bookmakers=book_list
                )
            ]

        out: list[dict[str, Any]] = []
        for fx in fixtures[:max_events]:
            fid = str(fx.get("fixtureId") or "")
            if not fid:
                continue
            try:
                odds = self.fixture_odds(fid, bookmakers=books)
            except OddsPapiError:
                continue
            if not isinstance(odds, dict) or not odds.get("bookmakerOdds"):
                # Still emit shell event? Skip empty — no props to rank
                continue
            # Prefer fixture participant names if odds omitted them
            for k in (
                "participant1Name",
                "participant2Name",
                "startTime",
                "tournamentId",
                "tournamentName",
            ):
                if not odds.get(k) and fx.get(k) is not None:
                    odds[k] = fx[k]
            event = self.odds_to_event(
                odds, sport=sport, market_filter=markets, bookmakers=book_list
            )
            if event.get("bookmakers"):
                out.append(event)
        return out


def _iso_z(value: Any) -> str:
    if not value:
        return ""
    s = str(value)
    if s.endswith(".000Z"):
        return s.replace(".000Z", "Z")
    return s


def _default_fixtures_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / "fixtures", Path.cwd() / "fixtures"]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OddsPapiError(f"Demo fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
