"""CSV / JSON export helpers (flat CSV + board JSON for the web UI)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from prizepicks_oddsshark.ranker import RankedEdge

# Fields the GitHub Pages board expects on each edge row.
BOARD_EDGE_KEYS = (
    "player",
    "market",
    "side",
    "pp_line",
    "book_line",
    "line_diff",
    "tier",
    "fair_prob",
    "offered_prob",
    "edge_pct",
    "book",
    "game",
    "sport",
    "commence_time",
    "event_id",
    "adjusted",
    "pp_price",
)


def edge_to_board_row(row: RankedEdge, *, sport: str | None = None) -> dict[str, Any]:
    """Serialize a ranked edge for the web board (includes game + sport)."""
    return {
        "player": row.player,
        "market": row.market,
        "side": row.side,
        "pp_line": row.pp_line,
        "book_line": row.book_line,
        "line_diff": row.line_diff,
        "tier": row.tier,
        "fair_prob": row.fair_prob,
        "offered_prob": row.offered_prob,
        "edge_pct": row.edge_pct,
        "book": row.book,
        "game": row.matchup,
        "sport": row.sport or sport or "",
        "commence_time": row.commence_time,
        "event_id": row.event_id,
        "adjusted": row.adjusted,
        "pp_price": row.pp_price,
    }


def build_board(
    rows: Sequence[RankedEdge],
    *,
    sport: str | None = None,
    book: str = "fanduel",
    demo: bool = False,
    sports: list[str] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Build the edges.json envelope consumed by docs/index.html."""
    if sports is not None:
        sport_list = list(sports)
    else:
        from_rows = []
        seen: set[str] = set()
        for r in rows:
            s = r.sport or sport or ""
            if s and s not in seen:
                seen.add(s)
                from_rows.append(s)
        sport_list = from_rows or ([sport] if sport else [])
    return {
        "updated_at": updated_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "pp-odds",
        "mode": "demo" if demo else "live",
        "book": book,
        "sports": sport_list,
        "count": len(rows),
        "edges": [edge_to_board_row(r, sport=sport) for r in rows],
    }


def merge_boards(*boards: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple board payloads (e.g. NBA + NFL) into one ranked board."""
    edges: list[dict[str, Any]] = []
    sports: list[str] = []
    book = "fanduel"
    mode = "live"
    for board in boards:
        book = board.get("book") or book
        if board.get("mode") == "demo":
            mode = "demo"
        for s in board.get("sports") or []:
            if s not in sports:
                sports.append(s)
        edges.extend(board.get("edges") or [])
    edges.sort(key=lambda e: float(e.get("edge_pct") or 0), reverse=True)
    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "pp-odds",
        "mode": mode,
        "book": book,
        "sports": sports,
        "count": len(edges),
        "edges": edges,
    }


def export_rows(
    rows: Sequence[RankedEdge],
    path: str | Path,
    *,
    sport: str | None = None,
    book: str = "fanduel",
    demo: bool = False,
    sports: list[str] | None = None,
) -> Path:
    """Write ranked edges to .csv (flat) or .json (board envelope for the web UI)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()
    if suffix == ".json":
        board = build_board(rows, sport=sport, book=book, demo=demo, sports=sports)
        out.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    elif suffix == ".csv":
        data = [r.to_dict() for r in rows]
        if not data:
            out.write_text("", encoding="utf-8")
            return out
        fieldnames = list(data[0].keys())
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
    else:
        raise ValueError(f"Unsupported export format '{suffix}' — use .csv or .json")
    return out
