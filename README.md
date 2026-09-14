# PrizePicksOddsShark

CLI that compares **PrizePicks** and **Underdog Fantasy** player props to a sportsbook (**FanDuel** by default) using **[The Odds API](https://the-odds-api.com/)** (primary), then ranks by **edge**. Sports: NFL, NCAAF, NBA, NCAAB, MLB, NHL (PGA skipped). OddsPapi remains an optional `--provider oddspapi`.

> **Personal research only.** Respect PrizePicks / sportsbook Terms of Service and your local laws. This tool does not place bets, scrape sites, or guarantee profit. Odds data comes from OddsPapi / The Odds API (no scraping).

## Features

- **PrizePicks + Underdog** in one Odds API pull (`regions=us,us_dfs`, `bookmakers=fanduel,prizepicks,underdog`) — board toggle is client-side and does **not** double credits
- **OddsPapi** live provider: tournaments → fixtures → odds (DFS + `fanduel`), mapped into the internal event/prop shape used by the ranker
- Fair odds from FanDuel (or Pinnacle on legacy provider)
- American → implied, multiplicative two-way de-vig, optional line-mismatch adjustment
- Rank by edge % with `--min-edge` (default **2%**)
- Disk cache (TTL ~8 minutes; markets catalog cached longer) to save API credits
- `--demo` mode with JSON fixtures (no API key / offline)
- Multi-sport board: NFL, NCAAF, NBA, NCAAB, MLB, NHL (PGA skipped — Odds API outrights only, no player props)
- **Weekly Thu cron** (NFL+NCAAF) + manual `workflow_dispatch` sport checkboxes
- Board multi-sport checkboxes (localStorage) + Platform toggle — client-side, no extra credits
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
- Requests `fanduel,prizepicks,underdog` together (same `us_dfs` region — not 2× credits for both DFS books)
- Caps `--max-events` per sport
- Disk-caches fixtures/odds (~8 min) and the markets catalog (days)

Use `--lean`; prefer the **weekly Thu cron** (football) or selective manual checkboxes. Watch the printed request counter after live runs.

**Credit tip (weekly football):** NFL `--max-events 16` + NCAAF `--max-events 25`, `--lean`, `--dfs both` ≈ **~125 credits/week** on The Odds API (one pull covers PrizePicks + Underdog). Other sports default to `--max-events 8` when checked on a manual run.

**Board refresh modes:**
- **Schedule** `0 15 * * 4` (Thu 8am America/Phoenix / MST year-round): NFL + NCAAF only, higher max-events, lean, dfs both.
- **Manual** Actions → Run workflow: boolean sport checkboxes (NFL/NCAAF/NBA/NCAAB/MLB/NHL); if none checked, defaults to NFL+NCAAF. PGA is not offered (no prop markets).
- Commence-time Thu–Mon filter is **not** applied (messy across providers); Thu-morning cron + max-events approximates the football slate.

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

# Export board JSON (demo = PrizePicks fixtures; live default --dfs both)
pp-odds --demo --dfs prizepicks --export docs/data/edges.json
pp-odds --provider theoddsapi --sport basketball_nba,americanfootball_nfl,americanfootball_ncaaf \
  --lean --max-events 2 --dfs both --export docs/data/edges.json
```

Also: `python -m prizepicks_oddsshark --demo`

### Slip advisor

Approximate PrizePicks **Power** / **Flex** EV given independent hit probabilities (use book/fair probs). Payouts can change in-app.

```bash
pp-odds slip --probs 0.55,0.58,0.52
pp-odds slip --from-board docs/data/edges.json --top 4
```

On the Pages board: use the **Platform** toggle and **Sports** multi-checkboxes (persisted in localStorage as `pp-odds-dfs-platform` / `pp-odds-sport-filters`), check 2–6 rows from the active platform (or paste probs) → **Rank slips**. Highest EV is highlighted. Toggling platform/sports does not re-fetch odds or spend credits. Default: all sports present in `edges.json` are checked.

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
| `--dfs` | `both` | `prizepicks`, `underdog`, or `both` (one API pull) |
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
  .github/workflows/update-edges.yml   # Thu cron + workflow_dispatch sport checkboxes
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
2. **Secret** — Actions secret `ODDS_API_KEY` (The Odds API). Optional: `ODDSPAPI_API_KEY`.
3. **Refresh** — weekly Thu cron (NFL+NCAAF) or **Actions → Update edges board → Run workflow** (pick sports via checkboxes)

The workflow fetches each selected sport with its own max-events, merges into one `docs/data/edges.json`, and commits only when it changes (`[skip ci]`).

### Local export

```bash
pp-odds --demo --export docs/data/edges.json
pp-odds --provider theoddsapi --sport americanfootball_nfl,americanfootball_ncaaf \
  --lean --max-events 16 --dfs both --export docs/data/edges.json
```

## College football (NCAAF)

Weekly scheduled refresh includes **full NCAAF** alongside NFL (no Nebraska-only filter; `--max-events 25`). Optional CLI `--team Nebraska` still works for local college-only pulls.

## PGA / golf

**Not supported.** The Odds API golf keys are tournament **outrights** only (`golf_pga_championship_winner`, Masters, etc.) — no player-prop markets for PrizePicks/Underdog lean edges. Workflow and board omit PGA checkboxes.

## Limitations / quirks

- Matching is name-normalized string equality; nicknames / injuries / DNP are not handled.
- OddsPapi market mapping is name-based (`Over Under Player Points…` → `player_points`). Specialty / quarter lines are skipped.
- **PrizePicks coverage on OddsPapi can be sparse** for some fixtures (FanDuel props may exist without PP). Empty boards with working auth are expected in those cases — not an auth failure.
- Participant1/2 are treated as away/home for matchup display.
- Slip EV assumes independence and approximate multipliers.
- No portfolio / correlation / entry sizing beyond the slip advisor.

## License

MIT — for personal research. You are responsible for compliance with local law and all third-party ToS.
