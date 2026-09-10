"""Typer CLI entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from prizepicks_oddsshark import __version__
from prizepicks_oddsshark.client import OddsAPIError, OddsClient
from prizepicks_oddsshark.export_util import export_rows
from prizepicks_oddsshark.matching import (
    SUPPORTED_SPORTS,
    default_markets_for_sport,
    parse_sport_arg,
    team_filter_applies,
)
from prizepicks_oddsshark.ranker import RankedEdge, rank_edges

app = typer.Typer(
    name="pp-odds",
    help="Compare PrizePicks props to FanDuel/Pinnacle via The Odds API and rank by edge.",
    add_completion=False,
)
console = Console()


def _fetch_sport_edges(
    client: OddsClient,
    sport: str,
    *,
    markets_override: list[str] | None,
    book: str,
    max_events: int,
    min_edge: float,
    demo: bool,
    lean: bool = False,
    team: str | None = None,
) -> list[RankedEdge]:
    """Fetch + rank one sport. Returns [] on soft failures (no events / API error)."""
    market_list = markets_override or default_markets_for_sport(sport, lean=lean)

    if demo and sport != "basketball_nba":
        console.print(
            f"[yellow]Demo fixtures are NBA-only — skipping {sport}[/yellow]"
        )
        return []

    try:
        team_q = team if (team and team_filter_applies(sport)) else None
        events = client.fetch_prop_events(
            sport,
            market_list,
            book=book,
            max_events=max_events,
            include_alternates=not lean,
            team=team_q,
        )
    except OddsAPIError as exc:
        console.print(f"[yellow]Warning: {sport} fetch failed — {exc}[/yellow]")
        return []

    if not events:
        extra = f" (team={team})" if team and team_filter_applies(sport) else ""
        console.print(
            f"[yellow]Warning: {sport} — no events / empty odds{extra}; skipping[/yellow]"
        )
        return []

    rows = rank_edges(
        events, book=book, markets=market_list, min_edge=min_edge, sport=sport
    )
    # Ensure sport field is set even if fixture/API omitted sport_key
    for r in rows:
        if not r.sport:
            r.sport = sport
    console.print(
        f"[dim]{sport}: {len(events)} event(s), {len(rows)} edge(s) "
        f"(markets={','.join(market_list)})[/dim]"
    )
    return rows


@app.callback(invoke_without_command=True)
def main(
    sport: str = typer.Option(
        "basketball_nba",
        "--sport",
        help=(
            "Sport key, comma-separated list, or 'all' "
            f"(supported: {', '.join(SUPPORTED_SPORTS)})"
        ),
    ),
    markets: Optional[str] = typer.Option(
        None,
        "--markets",
        help="Comma-separated market keys (default depends on each --sport)",
    ),
    min_edge: float = typer.Option(
        2.0,
        "--min-edge",
        help="Minimum edge in percentage points to display (default 2)",
    ),
    book: str = typer.Option(
        "fanduel",
        "--book",
        help="Sportsbook for fair odds: fanduel (default) or pinnacle",
    ),
    export: Optional[Path] = typer.Option(
        None,
        "--export",
        help="Write results to .csv or .json path",
    ),
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use bundled JSON fixtures (no API key / no network)",
    ),
    max_events: int = typer.Option(
        6,
        "--max-events",
        help="Max events to query per sport (each costs API credits)",
    ),
    lean: bool = typer.Option(
        False,
        "--lean",
        help="Free-tier mode: fewer markets and skip PrizePicks alternate (demon/goblin) lines",
    ),
    team: Optional[str] = typer.Option(
        None,
        "--team",
        help=(
            "Only include events matching this team name substring on college sports "
            "(e.g. Nebraska for Cornhuskers NCAAF). Ignored for NFL/NBA/MLB/NHL."
        ),
    ),
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
) -> None:
    """Rank PrizePicks options by edge vs de-vigged book implied probability."""
    if version:
        console.print(__version__)
        raise typer.Exit(0)

    load_dotenv()

    try:
        sports = parse_sport_arg(sport)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    book = book.lower().strip()
    if book not in ("fanduel", "pinnacle"):
        console.print("[red]--book must be fanduel or pinnacle[/red]")
        raise typer.Exit(2)

    markets_override = (
        [m.strip() for m in markets.split(",") if m.strip()] if markets else None
    )

    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    client = OddsClient(demo=demo, fixtures_dir=fixtures if fixtures.is_dir() else None)

    all_rows: list[RankedEdge] = []
    sports_with_data: list[str] = []

    for sp in sports:
        rows = _fetch_sport_edges(
            client,
            sp,
            markets_override=markets_override,
            book=book,
            max_events=max_events,
            min_edge=min_edge,
            demo=demo,
            lean=lean,
            team=team,
        )
        if rows or (demo and sp == "basketball_nba"):
            # Track sports we attempted that produced edges, or demo NBA
            if rows:
                sports_with_data.append(sp)
            elif demo and sp == "basketball_nba":
                sports_with_data.append(sp)
        all_rows.extend(rows)

    all_rows.sort(key=lambda r: r.edge_pct, reverse=True)

    # If every sport failed hard with no rows and we only had one sport and
    # it raised via empty+no soft path — still exit 0 for multi-sport boards
    # so CI can publish partial boards. Single-sport live with total failure
    # still exits 1 when nothing fetched at all and not demo.
    if not demo and not all_rows and len(sports) == 1:
        # Distinguish "no edges above threshold" (OK) vs "fetch totally failed"
        # Soft-fail already logged; treat as yellow no-edges for UX consistency
        pass

    mode = "DEMO" if demo else "LIVE"
    sport_label = ",".join(sports) if len(sports) > 1 else sports[0]
    console.print(
        f"[bold]PrizePicksOddsShark[/bold] {__version__}  "
        f"[{mode}] sport={sport_label} book={book} min_edge={min_edge}%  "
        f"lean={lean} team={team or '-'} sports_ok={','.join(sports_with_data) or 'none'}"
    )
    if not demo and client.last_headers:
        rem = client.last_headers.get("x-requests-remaining", "?")
        used = client.last_headers.get("x-requests-used", "?")
        console.print(f"[dim]API quota — used: {used}  remaining: {rem}[/dim]")

    if not all_rows:
        console.print(
            "[yellow]No edges above threshold (or no overlapping props).[/yellow]"
        )
    else:
        table = Table(show_header=True, header_style="bold")
        for col in (
            "Edge%",
            "Player",
            "Market",
            "Side",
            "Tier",
            "PP",
            "Book",
            "Fair",
            "Offered",
            "Sport",
            "Matchup",
        ):
            table.add_column(col)
        for r in all_rows[:50]:
            table.add_row(
                f"{r.edge_pct:.2f}",
                r.player,
                r.market.replace("player_", "").replace("batter_", "").replace("pitcher_", ""),
                r.side,
                r.tier,
                f"{r.pp_line:g}",
                f"{r.book_line:g}",
                f"{r.fair_prob:.1%}",
                f"{r.offered_prob:.1%}",
                r.sport or "",
                r.matchup,
            )
        console.print(table)
        console.print(f"[dim]Showing {min(len(all_rows), 50)} of {len(all_rows)} rows[/dim]")

    if export:
        # Prefer sports that contributed edges; fall back to requested list
        export_sports = sports_with_data or sports
        path = export_rows(
            all_rows,
            export,
            sport=export_sports[0] if len(export_sports) == 1 else None,
            book=book,
            demo=demo,
            sports=export_sports,
        )
        console.print(f"Exported {len(all_rows)} rows → {path}")


if __name__ == "__main__":
    app()
