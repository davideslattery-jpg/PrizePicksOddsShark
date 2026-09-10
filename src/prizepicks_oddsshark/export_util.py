"""CSV / JSON export helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Sequence

from prizepicks_oddsshark.ranker import RankedEdge


def export_rows(rows: Sequence[RankedEdge], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = [r.to_dict() for r in rows]
    suffix = out.suffix.lower()
    if suffix == ".json":
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    elif suffix == ".csv":
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
