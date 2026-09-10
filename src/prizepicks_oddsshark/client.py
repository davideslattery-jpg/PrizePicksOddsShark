"""The Odds API v4 client with disk cache (TTL 5–10 min)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://api.the-odds-api.com"
DEFAULT_TTL = 480  # 8 minutes within the requested 5–10 min window


class OddsAPIError(RuntimeError):
    pass


class OddsClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache_dir: str | Path | None = None,
        cache_ttl: int | None = None,
        timeout: float = 30.0,
        demo: bool = False,
        fixtures_dir: str | Path | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.cache_ttl = int(cache_ttl or os.getenv("ODDS_CACHE_TTL") or DEFAULT_TTL)
        self.cache_dir = Path(cache_dir or os.getenv("ODDS_CACHE_DIR") or ".odds_cache")
        self.timeout = timeout
        self.demo = demo
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else _default_fixtures_dir()
        self.last_headers: dict[str, str] = {}
        if not demo:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:40]
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, key: str) -> Any | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        ts = payload.get("_cached_at", 0)
        if time.time() - ts > self.cache_ttl:
            return None
        return payload.get("data")

    def _write_cache(self, key: str, data: Any) -> None:
        path = self._cache_path(key)
        blob = {"_cached_at": time.time(), "data": data}
        path.write_text(json.dumps(blob), encoding="utf-8")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        if self.demo:
            raise OddsAPIError("Live HTTP disabled in demo mode")
        if not self.api_key:
            raise OddsAPIError(
                "ODDS_API_KEY is not set. Copy .env.example to .env or pass --demo."
            )
        cache_key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apiKey")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        q = dict(params)
        q["apiKey"] = self.api_key
        url = f"{BASE_URL}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=q)
            self.last_headers = {
                k.lower(): v
                for k, v in resp.headers.items()
                if k.lower().startswith("x-requests")
            }
            if resp.status_code == 401:
                raise OddsAPIError("Unauthorized — check ODDS_API_KEY")
            if resp.status_code == 429:
                raise OddsAPIError("Rate limited (429). Back off and retry.")
            if resp.status_code >= 400:
                raise OddsAPIError(f"API error {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
        self._write_cache(cache_key, data)
        return data

    def list_events(self, sport: str) -> list[dict[str, Any]]:
        if self.demo:
            return _load_fixture(self.fixtures_dir / "events_nba.json")
        return self._get(f"/v4/sports/{sport}/events", {})

    def event_odds(
        self,
        sport: str,
        event_id: str,
        *,
        regions: str,
        markets: str,
        bookmakers: str | None = None,
        odds_format: str = "american",
    ) -> dict[str, Any]:
        if self.demo:
            fixture = self.fixtures_dir / "event_odds_nba.json"
            data = _load_fixture(fixture)
            # Allow demo to ignore event_id mismatch for offline runs
            if isinstance(data, dict):
                return data
            raise OddsAPIError(f"Bad demo fixture: {fixture}")

        params: dict[str, Any] = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        return self._get(f"/v4/sports/{sport}/events/{event_id}/odds", params)

    def fetch_prop_events(
        self,
        sport: str,
        markets: list[str],
        *,
        book: str = "fanduel",
        max_events: int = 8,
    ) -> list[dict[str, Any]]:
        """List events, then pull FanDuel + PrizePicks props per event.

        Regions: `us` (or `eu` for pinnacle) + `us_dfs` for PrizePicks.
        Bookmakers filter keeps quota focused.
        """
        events = self.list_events(sport)
        if self.demo:
            return [self.event_odds(sport, "demo", regions="us,us_dfs", markets=",".join(markets))]

        # Include alternate markets for PrizePicks demons/goblins
        market_keys: list[str] = []
        for m in markets:
            market_keys.append(m)
            alt = f"{m}_alternate"
            if alt not in market_keys:
                market_keys.append(alt)
        markets_param = ",".join(market_keys)

        if book == "pinnacle":
            regions = "eu,us_dfs"
            books = "pinnacle,prizepicks"
        else:
            regions = "us,us_dfs"
            books = f"{book},prizepicks"

        out: list[dict[str, Any]] = []
        for ev in events[:max_events]:
            eid = ev["id"]
            try:
                odds = self.event_odds(
                    sport,
                    eid,
                    regions=regions,
                    markets=markets_param,
                    bookmakers=books,
                )
            except OddsAPIError:
                continue
            if odds:
                out.append(odds)
        return out


def _default_fixtures_dir() -> Path:
    # package → src/prizepicks_oddsshark → src → project root / fixtures
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "fixtures",
        Path.cwd() / "fixtures",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def _load_fixture(path: Path) -> Any:
    if not path.exists():
        raise OddsAPIError(f"Demo fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
