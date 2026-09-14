"""Odds provider selection (OddsPapi primary, The Odds API legacy)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from prizepicks_oddsshark.client import OddsAPIError, OddsClient
from prizepicks_oddsshark.oddspapi_client import OddsPapiClient, OddsPapiError


class PropEventsProvider(Protocol):
    last_headers: dict[str, str]

    def fetch_prop_events(
        self,
        sport: str,
        markets: list[str],
        *,
        book: str = "fanduel",
        max_events: int = 8,
        include_alternates: bool = True,
        team: str | None = None,
        dfs: str | list[str] | None = "both",
    ) -> list[dict[str, Any]]: ...


def resolve_provider(name: str | None) -> str:
    """Return 'oddspapi' | 'theoddsapi'. 'auto' prefers OddsPapi when keyed."""
    raw = (name or "auto").strip().lower()
    if raw in ("auto", ""):
        if os.getenv("ODDSPAPI_API_KEY"):
            return "oddspapi"
        if os.getenv("ODDS_API_KEY"):
            return "theoddsapi"
        # Default brand: OddsPapi (caller may still use --demo)
        return "oddspapi"
    if raw in ("oddspapi", "odds_papi", "op"):
        return "oddspapi"
    if raw in ("theoddsapi", "oddsapi", "the-odds-api", "legacy"):
        return "theoddsapi"
    raise ValueError(
        f"Unknown --provider {name!r}. Use auto, oddspapi, or theoddsapi."
    )


def make_client(
    provider: str,
    *,
    demo: bool = False,
    fixtures_dir: Path | None = None,
) -> PropEventsProvider:
    resolved = resolve_provider(provider)
    if demo:
        # Offline demo fixtures are The Odds API shaped (NBA).
        return OddsClient(demo=True, fixtures_dir=fixtures_dir)
    if resolved == "oddspapi":
        return OddsPapiClient(demo=False, fixtures_dir=fixtures_dir)
    return OddsClient(demo=False, fixtures_dir=fixtures_dir)


__all__ = [
    "OddsAPIError",
    "OddsPapiError",
    "PropEventsProvider",
    "make_client",
    "resolve_provider",
]
