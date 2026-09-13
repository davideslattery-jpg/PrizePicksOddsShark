# PrizePicksOddsShark

CLI that compares **PrizePicks** player props to a sportsbook (**FanDuel** by default) using **[OddsPapi](https://oddspapi.io/)** (primary), then ranks PrizePicks options by **edge** vs fair implied probability. Legacy [The Odds API](https://the-odds-api.com/) remains available via `--provider theoddsapi`.

> **Personal research only.** Respect PrizePicks / sportsbook Terms of Service and your local laws. This tool does not place bets, scrape sites, or guarantee profit. Odds data comes from OddsPapi / The Odds API (no scraping).

## Features

- **OddsPapi** live provider: tournaments → fixtures → odds (`prizepicks` + `fanduel`), mapped into the internal event/prop shape used by the ranker
- Fair odds from FanDuel (or Pinnacle on legacy provider)
- American → implied, multiplicative two-way de-vig, optional line-mismatch adjustment
- Rank by edge % with `--min-edge` (default **2%**)
- Disk cache (TTL ~8 minutes; markets catalog cached longer) to save API credits
- `--demo` mode with JSON fixtures (no API key / offline)
- Multi-sport board: NBA, NFL, MLB, NHL (+ NCAAF/NCAAB when available)
- **Manual-only** GitHub Action refresh (no cron) for free-tier conservation
- **Slip advisor**: Power / Flex EV ranking from pick probabilities (`pp-odds slip` + board UI)
- Optional `--export` to CSV or board JSON (GitHub Pages under `docs/`)

## Setup

```bash
cd PrizePicksOddsShark
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### API key (OddsPapi)

1. Create a key at [https://oddspapi.io/](https://oddspapi.io/)
2. Copy `.env.example` → `.env` and set `ODDSPAPI_API_KEY=...`
3. **Never commit `.env`** (already in `.gitignore`)

Optional legacy: set `ODDS_API_KEY` and pass `--provider theoddsapi`.

### Credit / quota warning

OddsPapi free tier is limited (~250 req/mo). This CLI:

- Filters to needed tournaments (NBA / NFL / NCAAF)
- Requests only `prizepicks,fanduel`
- Caps `--max-events` per sport
- Disk-caches fixtures/odds (~8 min) and the markets catalog (days)

Use `--lean` and keep refreshes **manual**. Watch the printed request counter after live runs.

**Free-tier board mode (GitHub Action):** NBA + NFL + Nebraska NCAAF, `--lean`, `--max-events 2`, **workflow_dispatch only** (no schedule).

## Usage

```bash
# Offline demo (no key) — NBA fixtures only
pp-odds --demo

# Live via OddsPapi (default when ODDSPAPI_API_KEY is set)
pp-odds --provider oddspapi --sport basketball_nba,americanfootball_nfl,americanfootball_ncaaf \
  --lean --team Nebraska --max-events 2

# Auto provider: OddsPapi if keyed, else The Odds API
pp-odds --provider auto --sport americanfootball_nfl --lean --max-events 2

# Legacy The Odds API
pp-odds --provider theoddsapi --sport basketball_nba

# Export board JSON
pp-odds --demo --export docs/data/edges.json
```

Also: `python -m prizepicks_oddsshark --demo`

### Slip advisor

Approximate PrizePicks **Power** / **Flex** EV given independent hit probabilities (use book/fair probs). Payouts can change in-app.

```bash
pp-odds slip --probs 0.55,0.58,0.52
pp-odds slip --from-board docs/data/edges.json --top 4
```

On the Pages board: check 2–6 rows (or paste probs) → **Rank slips**. Highest EV is highlighted.

**Independence assumption:** correlated teammates/games are not modeled. Research only.

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | `auto` | `auto` / `oddspapi` / `theoddsapi` |
| `--sport` | `basketball_nba` | Single key, comma list, or `all` |
| `--markets` | sport defaults | Comma-separated market keys |
| `--min-edge` | `2` | Minimum edge in **percentage points** |
| `--book` | `fanduel` | `fanduel` or `pinnacle` (pinnacle: legacy provider) |
| `--export` | — | Path ending in `.csv` or `.json` |
| `--demo` | off | Use bundled fixtures |
| `--max-events` | `6` | Cap live event fetches **per sport** |
| `--lean` | off | Fewer markets; skip PP alternates (legacy) |
| `--team` | — | College team substring filter (e.g. Nebraska) |
| `--version` | — | Print version |

## Ranking explanation

1. **American → raw implied**
   - Negative odds \(o\): \(|o| / (|o| + 100)\)
   - Positive odds \(o\): \(100 / (o + 100)\)
2. **De-vig (multiplicative, two-way)**  
   For Over/Under raw probs \(p_o, p_u\):  
   \(\text{fair}_o = p_o / (p_o + p_u)\), \(\text{fair}_u = p_u / (p_o + p_u)\) so they sum to 1.
3. **PrizePicks offered probability**
   - **Standard** lines: compare fair prob to **0.5** (even-money DFS proxy).
   - **Demon / goblin** (legacy `*_alternate`): use American prices when present.
4. **Edge %** = \((\text{fair} - \text{offered}) \times 100\) (percentage points).

### Line mismatch adjustment

When the PrizePicks line differs from the nearest sportsbook line, fair probability is adjusted with a simple normal latent-stat heuristic. Identical lines skip the adjustment.

## Project layout

```
PrizePicksOddsShark/
  pyproject.toml
  README.md
  .env.example
  .github/workflows/update-edges.yml   # workflow_dispatch only
  fixtures/                 # demo JSON + fixtures/oddspapi/
  docs/                     # GitHub Pages site + slip advisor
  src/prizepicks_oddsshark/
    cli.py                  # Typer entry (pp-odds, pp-odds slip)
    oddspapi_client.py      # OddsPapi + adapter
    client.py               # Legacy The Odds API + disk cache
    providers.py            # provider selection
    matching.py / probability.py / ranker.py
    slip_optimizer.py       # Power/Flex EV
    export_util.py
  tests/                    # pytest (offline)
```

## Tests

```bash
pytest -q
```

All tests run **offline** (no API key / no network).

## Live board (GitHub Pages)

**https://davideslattery-jpg.github.io/PrizePicksOddsShark/**

### One-time setup

1. **Enable Pages** — Settings → Pages → Deploy from `main` / `/docs`
2. **Secret** — Actions secret `ODDSPAPI_API_KEY` (OddsPapi). Legacy `ODDS_API_KEY` optional.
3. **Manual refresh** — **Actions → Update edges board → Run workflow**

**No scheduled runs.** The workflow commits `docs/data/edges.json` only when it changes (`[skip ci]`).

### Local export

```bash
pp-odds --demo --export docs/data/edges.json
pp-odds --provider oddspapi --sport basketball_nba,americanfootball_nfl,americanfootball_ncaaf \
  --lean --team Nebraska --max-events 2 --export docs/data/edges.json
```

## Nebraska Cornhuskers

Free-tier board includes NCAAF filtered to **Nebraska** only (`--team Nebraska`).

## Limitations / quirks

- Matching is name-normalized string equality; nicknames / injuries / DNP are not handled.
- OddsPapi market mapping is name-based (`Over Under Player Points…` → `player_points`). Specialty / quarter lines are skipped.
- **PrizePicks coverage on OddsPapi can be sparse** for some fixtures (FanDuel props may exist without PP). Empty boards with working auth are expected in those cases — not an auth failure.
- Participant1/2 are treated as away/home for matchup display.
- Slip EV assumes independence and approximate multipliers.
- No portfolio / correlation / entry sizing beyond the slip advisor.

## License

MIT — for personal research. You are responsible for compliance with local law and all third-party ToS.
