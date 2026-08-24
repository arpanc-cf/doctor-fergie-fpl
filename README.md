# Doctor Fergie

Local, single-user Fantasy Premier League dashboard. See `FPL_Dashboard_Project_Brief.md` (original brief) for full scope.

## Run

```bash
source .venv/bin/activate
streamlit run app.py
```

Opens at http://localhost:8501.

## Status

- **Phase 1 (done)**: bootstrap-static + fixtures fetch, SQLite cache with 1h
  refresh-if-stale + manual refresh button + stale-fallback on API failure,
  sortable/filterable player table (position, team, price, name search).
- **Phase 2 (done)**: FPL team ID input (persisted locally), squad/bank/chip
  view per gameweek, estimated free transfers, season points/rank chart.
- **Phase 3 (done)**: FDR ticker (color-coded, configurable GW window),
  best/worst fixture runs per team, per-gameweek fixture list.
- **Phase 4 (done)**: PuLP squad optimizer (best XI + formation under budget/
  club-limit constraints, using a form + points-per-game proxy score), and a
  greedy best-transfer suggester for your saved team (flags hits beyond free
  transfers).
- **Phase 5 (done)**: captain/vice-captain recommendation for your actual
  starting XI (form/PPG adjusted for that gameweek's fixture, so blanks
  score 0 and doubles count both fixtures), a chip-timing helper that scans
  the season for blank/double gameweeks, and the refresh button now covers
  every tab including the Optimizer's team-data loads (previously missed).

All five phases from the project brief are built. Natural next steps if you
want to keep going: a real points-prediction model in place of the form/PPG
proxy, multi-transfer (not just greedy single-swap) optimization, and
mobile-friendlier layout.

## Layout

- `app.py` — Streamlit UI (all four tabs).
- `src/fpl_api.py` — FPL API client (all known endpoints, error handling).
- `src/cache.py` — SQLite key/value cache with refresh-if-stale + fallback.
- `src/config.py` — local team ID persistence (`data/config.json`).
- `src/team.py` — squad/season-history views derived from entry/picks data.
- `src/fixtures.py` — FDR ticker, fixture list, and chip-window detection.
- `src/optimizer.py` — PuLP squad optimizer + greedy transfer suggester.
- `src/recommend.py` — captain/vice-captain recommendation.
- `data/fpl_cache.db` — local cache (gitignored).
