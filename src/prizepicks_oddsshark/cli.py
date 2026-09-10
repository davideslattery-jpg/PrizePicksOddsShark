"""Typer CLI entry point."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from prizepicks_oddsshark import __version__
from prizepicks_oddsshark.client import OddsAPIError, OddsClient
from prizepicks_oddsshark.export_util import export_rows
from prizepicks_oddsshark.matching import default_markets_for_sport
from prizepicks_oddsshark.ranker import rank_edges

app = typer.Typer(
    name="pp-odds",
    help="Compare PrizePicks props to FanDuel/Pinnacle via The Odds API and rank by edge.",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(
    sport: str = typer.Option(
        "basketball_nba",
        "--sport",
        help="Sport key: basketball_nba or americanfootball_nfl",
    ),
    markets: Optional[str] = typer.Option(
        None,
        "--markets",
        help="Comma-separated market keys (default depends on --sport)",
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
        help="Max events to query (each costs API credits)",
    ),
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
) -> None:
    """Rank PrizePicks options by edge vs de-vigged book implied probability."""
    if version:
        console.print(__version__)
        raise typer.Exit(0)

    load_dotenv()

    if sport not in ("basketball_nba", "americanfootball_nfl"):
        console.print(
            f"[red]Unsupported sport '{sport}'. Use basketball_nba or americanfootball_nfl.[/red]"
        )
        raise typer.Exit(2)

    book = book.lower().strip()
    if book not in ("fanduel", "pinnacle"):
        console.print("[red]--book must be fanduel or pinnacle[/red]")
        raise typer.Exit(2)

    market_list = (
        [m.strip() for m in markets.split(",") if m.strip()]
        if markets
        else default_markets_for_sport(sport)
    )

    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    client = OddsClient(demo=demo, fixtures_dir=fixtures if fixtures.is_dir() else None)

    try:
        events = client.fetch_prop_events(
            sport, market_list, book=book, max_events=max_events
        )
    except OddsAPIError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    rows = rank_edges(events, book=book, markets=market_list, min_edge=min_edge)

    mode = "DEMO" if demo else "LIVE"
    console.print(
        f"[bold]PrizePicksOddsShark[/bold] {__version__}  "
        f"[{mode}] sport={sport} book={book} min_edge={min_edge}%  "
        f"markets={','.join(market_list)}"
    )
    if not demo and client.last_headers:
        rem = client.last_headers.get("x-requests-remaining", "?")
        used = client.last_headers.get("x-requests-used", "?")
        console.print(f"[dim]API quota — used: {used}  remaining: {rem}[/dim]")

    if not rows:
        console.print("[yellow]No edges above threshold (or no overlapping props).[/yellow]")
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
            "Matchup",
        ):
            table.add_column(col)
        for r in rows[:50]:
            table.add_row(
                f"{r.edge_pct:.2f}",
                r.player,
                r.market.replace("player_", ""),
                r.side,
                r.tier,
                f"{r.pp_line:g}",
                f"{r.book_line:g}",
                f"{r.fair_prob:.1%}",
                f"{r.offered_prob:.1%}",
                r.matchup,
            )
        console.print(table)
        console.print(f"[dim]Showing {min(len(rows), 50)} of {len(rows)} rows[/dim]")

    if export:
        path = export_rows(rows, export, sport=sport, book=book, demo=demo)
        console.print(f"Exported {len(rows)} rows → {path}")


if __name__ == "__main__":
    app()
