"""Typer CLI entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from prizepicks_oddsshark import __version__
from prizepicks_oddsshark.client import OddsAPIError
from prizepicks_oddsshark.export_util import export_rows
from prizepicks_oddsshark.matching import (
    SUPPORTED_SPORTS,
    default_markets_for_sport,
    parse_sport_arg,
    team_filter_applies,
)
from prizepicks_oddsshark.oddspapi_client import OddsPapiError
from prizepicks_oddsshark.providers import make_client, resolve_provider
from prizepicks_oddsshark.ranker import RankedEdge, parse_dfs_arg, rank_edges
from prizepicks_oddsshark.slip_optimizer import (
    probs_from_board_edges,
    rank_slip_types,
    suggest_slips_from_edges,
)

app = typer.Typer(
    name="pp-odds",
    help=(
        "Compare PrizePicks / Underdog Fantasy props to FanDuel via OddsPapi "
        "(default) or The Odds API; rank by edge. Also: slip EV advisor."
    ),
    add_completion=False,
    invoke_without_command=True,
)
console = Console()

_DFS_SHORT = {"prizepicks": "PP", "underdog": "UD"}


def _fetch_sport_edges(
    client: object,
    sport: str,
    *,
    markets_override: list[str] | None,
    book: str,
    max_events: int,
    min_edge: float,
    demo: bool,
    lean: bool = False,
    team: str | None = None,
    dfs_platforms: list[str] | None = None,
) -> list[RankedEdge]:
    """Fetch + rank one sport. Returns [] on soft failures (no events / API error)."""
    market_list = markets_override or default_markets_for_sport(sport, lean=lean)
    platforms = dfs_platforms or ["prizepicks"]

    if demo and sport != "basketball_nba":
        console.print(
            f"[yellow]Demo fixtures are NBA-only — skipping {sport}[/yellow]"
        )
        return []

    try:
        team_q = team if (team and team_filter_applies(sport)) else None
        events = client.fetch_prop_events(  # type: ignore[attr-defined]
            sport,
            market_list,
            book=book,
            max_events=max_events,
            include_alternates=not lean,
            team=team_q,
            dfs=platforms,
        )
    except (OddsAPIError, OddsPapiError) as exc:
        console.print(f"[yellow]Warning: {sport} fetch failed — {exc}[/yellow]")
        return []

    if not events:
        extra = f" (team={team})" if team and team_filter_applies(sport) else ""
        console.print(
            f"[yellow]Warning: {sport} — no events / empty odds{extra}; skipping[/yellow]"
        )
        return []

    rows = rank_edges(
        events,
        book=book,
        markets=market_list,
        min_edge=min_edge,
        sport=sport,
        dfs_platforms=platforms,
    )
    for r in rows:
        if not r.sport:
            r.sport = sport
    console.print(
        f"[dim]{sport}: {len(events)} event(s), {len(rows)} edge(s) "
        f"(markets={','.join(market_list)} dfs={','.join(platforms)})[/dim]"
    )
    return rows


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
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
    provider: str = typer.Option(
        "auto",
        "--provider",
        help="Odds provider: auto (OddsPapi if keyed), oddspapi, or theoddsapi (legacy)",
    ),
    dfs: str = typer.Option(
        "both",
        "--dfs",
        help="DFS platforms to rank: prizepicks, underdog, or both (default both; one API pull)",
    ),
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
) -> None:
    """Rank PrizePicks / Underdog options by edge vs de-vigged book implied probability."""
    if version:
        console.print(__version__)
        raise typer.Exit(0)

    # Subcommands (e.g. slip) handle themselves
    if ctx.invoked_subcommand is not None:
        return

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

    try:
        dfs_platforms = parse_dfs_arg(dfs)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if demo and dfs_platforms == ["underdog"]:
        console.print(
            "[yellow]Demo fixtures are PrizePicks-only — underdog edges will be empty[/yellow]"
        )

    try:
        resolved = resolve_provider(provider)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    markets_override = (
        [m.strip() for m in markets.split(",") if m.strip()] if markets else None
    )

    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    client = make_client(
        resolved if not demo else "theoddsapi",
        demo=demo,
        fixtures_dir=fixtures if fixtures.is_dir() else None,
    )

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
            dfs_platforms=dfs_platforms,
        )
        if rows:
            sports_with_data.append(sp)
        elif demo and sp == "basketball_nba":
            sports_with_data.append(sp)
        all_rows.extend(rows)

    all_rows.sort(key=lambda r: r.edge_pct, reverse=True)

    mode = "DEMO" if demo else "LIVE"
    sport_label = ",".join(sports) if len(sports) > 1 else sports[0]
    provider_label = "demo-fixtures" if demo else resolved
    console.print(
        f"[bold]PrizePicksOddsShark[/bold] {__version__}  "
        f"[{mode}] provider={provider_label} sport={sport_label} book={book} "
        f"min_edge={min_edge}% lean={lean} dfs={','.join(dfs_platforms)} "
        f"team={team or '-'} "
        f"sports_ok={','.join(sports_with_data) or 'none'}"
    )
    if not demo and getattr(client, "last_headers", None):
        rem = client.last_headers.get("x-requests-remaining", "?")
        used = client.last_headers.get("x-requests-used", "?")
        console.print(f"[dim]API quota-ish — used: {used}  remaining: {rem}[/dim]")

    if not all_rows:
        console.print(
            "[yellow]No edges above threshold (or no overlapping props).[/yellow]"
        )
        if not demo and resolved == "oddspapi":
            console.print(
                "[dim]Tip: OddsPapi may lack PrizePicks/Underdog markets for some fixtures; "
                "empty slate is OK when auth works. Try --demo or another slate.[/dim]"
            )
    else:
        table = Table(show_header=True, header_style="bold")
        for col in (
            "Edge%",
            "DFS",
            "Player",
            "Market",
            "Side",
            "Tier",
            "Line",
            "Book",
            "Fair",
            "Offered",
            "Sport",
            "Matchup",
        ):
            table.add_column(col)
        for r in all_rows[:50]:
            plat = (r.platform or "prizepicks").lower()
            table.add_row(
                f"{r.edge_pct:.2f}",
                _DFS_SHORT.get(plat, plat),
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
        export_sports = sports_with_data or sports
        path = export_rows(
            all_rows,
            export,
            sport=export_sports[0] if len(export_sports) == 1 else None,
            book=book,
            demo=demo,
            sports=export_sports,
            dfs_platforms=dfs_platforms,
        )
        console.print(f"Exported {len(all_rows)} rows → {path}")


@app.command("slip")
def slip_cmd(
    probs: Optional[str] = typer.Option(
        None,
        "--probs",
        help="Comma-separated hit probabilities, e.g. 0.55,0.58,0.52 (2–6 values)",
    ),
    from_board: Optional[Path] = typer.Option(
        None,
        "--from-board",
        help="Board JSON (edges.json); uses top edges' fair_prob",
    ),
    suggest_from_board: Optional[Path] = typer.Option(
        None,
        "--suggest-from-board",
        help="Board JSON; auto-search best 2–6 pick Power/Flex combos by EV",
    ),
    platform: str = typer.Option(
        "prizepicks",
        "--platform",
        help="When suggesting: prizepicks, underdog, or both",
    ),
    top: int = typer.Option(
        4,
        "--top",
        help="With --from-board: top edges (2–6). With --suggest-from-board: # suggestions",
    ),
    pool_size: int = typer.Option(
        16,
        "--pool-size",
        help="Candidate pool size (top K by edge) for --suggest-from-board",
    ),
) -> None:
    """Rank Power/Flex slip types by EV given independent pick probabilities."""
    load_dotenv()

    if suggest_from_board is not None:
        path = suggest_from_board
        if not path.exists():
            console.print(f"[red]Board not found: {path}[/red]")
            raise typer.Exit(2)
        data = json.loads(path.read_text(encoding="utf-8"))
        edges = data.get("edges") if isinstance(data, dict) else data
        if not isinstance(edges, list):
            console.print("[red]Board JSON missing edges[][/red]")
            raise typer.Exit(2)
        suggestions = suggest_slips_from_edges(
            edges,
            platform=platform,
            pool_size=pool_size,
            top=max(1, min(top, 20)),
        )
        plat = platform.lower().strip() or "prizepicks"
        console.print(
            f"[bold]Suggest slips[/bold] platform={plat}  "
            f"pool≤{pool_size}  showing {len(suggestions)}  "
            f"(junk: edge>15% or |line Δ|>5; independence assumed)"
        )
        if not suggestions:
            console.print("[yellow]No suggestions (need ≥2 non-junk edges with fair_prob).[/yellow]")
            raise typer.Exit(0)
        table = Table(show_header=True, header_style="bold")
        for col in ("#", "Slip", "EV/$1", "Picks"):
            table.add_column(col)
        for i, s in enumerate(suggestions, start=1):
            pick_txt = "; ".join(
                f"{p.get('player')} {p.get('side')} {p.get('pp_line')} {p.get('market')}"
                for p in s["picks"]
            )
            table.add_row(str(i), s["label"], f"{s['ev']:+.4f}", pick_txt)
        console.print(table)
        return

    values: list[float]
    if probs:
        try:
            values = [float(x.strip()) for x in probs.split(",") if x.strip()]
        except ValueError as exc:
            console.print("[red]Could not parse --probs[/red]")
            raise typer.Exit(2) from exc
    elif from_board:
        path = from_board
        if not path.exists():
            console.print(f"[red]Board not found: {path}[/red]")
            raise typer.Exit(2)
        data = json.loads(path.read_text(encoding="utf-8"))
        edges = data.get("edges") if isinstance(data, dict) else data
        if not isinstance(edges, list):
            console.print("[red]Board JSON missing edges[][/red]")
            raise typer.Exit(2)
        try:
            values = probs_from_board_edges(edges, top=max(2, min(top, 6)))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2) from exc
        console.print(
            f"[dim]Using top {len(values)} board fair_prob(s): "
            f"{', '.join(f'{p:.3f}' for p in values)}[/dim]"
        )
    else:
        console.print("[red]Provide --probs, --from-board, or --suggest-from-board[/red]")
        raise typer.Exit(2)

    try:
        ranked = rank_slip_types(values)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    console.print(
        f"[bold]Slip advisor[/bold] n={len(values)}  "
        f"probs=[{', '.join(f'{p:.3f}' for p in values)}]  "
        f"(independence assumed; payouts approximate)"
    )
    table = Table(show_header=True, header_style="bold")
    for col in ("Rank", "Slip", "EV/$1", "E[payout]", "P(cash)", "P(max)", "Max mult"):
        table.add_column(col)
    for i, row in enumerate(ranked, start=1):
        marker = " ★" if i == 1 else ""
        table.add_row(
            str(i),
            f"{row.label}{marker}",
            f"{row.ev:+.4f}",
            f"{row.expected_payout:.4f}",
            f"{row.p_cash:.1%}",
            f"{row.p_max:.1%}",
            f"{row.multiplier_max:g}x",
        )
    console.print(table)
    best = ranked[0]
    console.print(
        f"[green]Recommended:[/green] {best.label}  "
        f"EV={best.ev:+.4f} per $1  P(cash)={best.p_cash:.1%}"
    )


if __name__ == "__main__":
    app()
