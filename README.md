# PrizePicksOddsShark

CLI that compares **PrizePicks** player props to a sportsbook (**FanDuel** by default, or **Pinnacle**) using [The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/), then ranks PrizePicks options by **edge** vs fair implied probability.

> **Personal research only.** Respect PrizePicks / sportsbook Terms of Service and your local laws. This tool does not place bets, scrape sites, or guarantee profit. Odds data comes solely from The Odds API (no scraping).

## Features

- Fetch player props per event: `GET /v4/sports/{sport}/events` → `GET /v4/sports/{sport}/events/{eventId}/odds`
- PrizePicks via bookmaker `prizepicks`, region `us_dfs` (demons/goblins in `*_alternate` markets)
- Fair odds from FanDuel (`fanduel`, region `us`) or Pinnacle (`pinnacle`, region `eu`)
- American → implied, multiplicative two-way de-vig, optional line-mismatch adjustment
- Rank by edge % with `--min-edge` (default **2%**)
- Disk cache (TTL ~8 minutes) to save API credits
- `--demo` mode with JSON fixtures (no API key)
- Optional `--export` to CSV or JSON

## Setup

```bash
cd PrizePicksOddsShark
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### API key

1. Create a free key at [https://the-odds-api.com/](https://the-odds-api.com/)
2. Copy `.env.example` → `.env` and set `ODDS_API_KEY=...`
3. **Never commit `.env`** (already in `.gitignore`)

### Credit / quota warning

Event prop calls cost **credits per market × region**. This CLI requests FanDuel (or Pinnacle) **plus** PrizePicks and includes `*_alternate` markets for demons/goblins. Use `--max-events` to limit spend, rely on the disk cache (5–10 min TTL), and watch response headers `x-requests-remaining` / `x-requests-used` printed after live runs. Empty responses generally do not consume quota.

## Usage

```bash
# Offline demo (no key)
pp-odds --demo

# Live NBA vs FanDuel, default markets, min edge 2%
pp-odds --sport basketball_nba

# NFL, custom markets, Pinnacle as fair book
pp-odds --sport americanfootball_nfl --book pinnacle \
  --markets player_pass_yds,player_rush_yds,player_reception_yds

# Stricter edge + export
pp-odds --demo --min-edge 3 --export edges.json
pp-odds --demo --export edges.csv
```

Also: `python -m prizepicks_oddsshark --demo`

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--sport` | `basketball_nba` | `basketball_nba` or `americanfootball_nfl` |
| `--markets` | sport defaults | Comma-separated Odds API market keys |
| `--min-edge` | `2` | Minimum edge in **percentage points** |
| `--book` | `fanduel` | `fanduel` or `pinnacle` |
| `--export` | — | Path ending in `.csv` or `.json` |
| `--demo` | off | Use bundled fixtures |
| `--max-events` | `6` | Cap live event fetches |
| `--version` | — | Print version |

## Ranking explanation

1. **American → raw implied**
   - Negative odds \(o\): \(|o| / (|o| + 100)\)
   - Positive odds \(o\): \(100 / (o + 100)\)
2. **De-vig (multiplicative, two-way)**  
   For Over/Under raw probs \(p_o, p_u\):  
   \(\text{fair}_o = p_o / (p_o + p_u)\), \(\text{fair}_u = p_u / (p_o + p_u)\) so they sum to 1.
3. **PrizePicks offered probability**
   - **Standard** lines: compare fair prob to **0.5** (even-money DFS proxy; PrizePicks does not post true American prices the same way sportsbooks do).
   - **Demon / goblin** (from `*_alternate`): use Odds API American prices. Per The Odds API, **goblins ≈ default odds**, **demons ≈ +100**.
4. **Edge %** = \((\text{fair} - \text{offered}) \times 100\) (percentage points). Rows below `--min-edge` are dropped; remaining rows sort descending by edge.

### Line mismatch adjustment

When the PrizePicks line differs from the nearest sportsbook line for the same player/market/side, fair probability is adjusted with a simple **normal / log-style** latent-stat model:

- Assume the counting stat is approximately \(\mathcal{N}(\mu, \sigma)\) with  
  \(\sigma = \max(|L_{\text{book}}| \cdot 0.15,\ 1.0)\).
- From fair \(P(\text{Over} \mid L_{\text{book}})\) recover a standardized threshold, then shift by  
  \((L_{\text{PP}} - L_{\text{book}}) / \sigma\) and re-evaluate the normal CDF.

This is a **heuristic** for small line gaps—not a full projection model. Identical lines skip the adjustment.

## Project layout

```
PrizePicksOddsShark/
  pyproject.toml
  README.md
  .env.example
  .gitignore
  fixtures/                 # demo JSON (events + event odds)
  src/prizepicks_oddsshark/
    cli.py                  # Typer entry (pp-odds)
    client.py               # Odds API + disk cache
    matching.py             # name/market normalize + match
    probability.py          # odds math + line adjust
    ranker.py               # edge ranking
    export_util.py          # CSV/JSON export
  tests/                    # pytest (offline)
```

## Tests

```bash
pytest -q
```

All tests run **offline** (no API key).

## Limitations / next steps

- Matching is name-normalized string equality; nicknames / injuries / DNP are not handled.
- Only NBA & NFL sport keys are wired in the CLI; markets list is a practical subset.
- Demon/goblin detection follows Odds API conventions (`+100` → demon on alternate markets).
- No portfolio / correlation / entry sizing; single-leg edge only.
- Live availability depends on The Odds API coverage for `us_dfs` / PrizePicks.

## License

MIT — for personal research. You are responsible for compliance with local law and all third-party ToS.
