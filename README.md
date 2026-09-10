# NFL Prop Predictor

Daily-refreshed statistical projections for NFL QB / RB / WR / TE props
(passing, rushing, and receiving stats), published as a free static
site via GitHub Pages and rebuilt every day by GitHub Actions.

## What it actually does

1. `scripts/fetch_data.py` pulls the current season's player-by-week stats
   and the league schedule from [nflverse](https://github.com/nflverse)
   via the `nfl_data_py` package (free, no API key needed).
2. `scripts/build_predictions.py` finds the next unplayed week and, for
   every QB/RB/WR/TE getting real usage, projects their key stats as:

   `projection = player's recency-weighted last-4-games average  x  opponent matchup multiplier`

   The opponent multiplier compares how much of that stat the upcoming
   opponent has allowed to that position recently vs. the league average,
   clipped to +/-25% so a fluky game doesn't distort things.
3. `scripts/generate_site.py` renders `docs/index.html` from the result.
4. The GitHub Actions workflow (`.github/workflows/daily.yml`) runs all
   three every day, then commits the refreshed `data/` and `docs/` files
   back to the repo.

**What this is not:** it has no idea about injuries, suspensions,
depth-chart changes, weather, or actual sportsbook lines. It's a
transparent statistical baseline for your own research, not a finished
edge — treat the numbers as a starting point to sanity-check against real
news, not a pick to bet blind.

## One-time setup after you upload this

1. **Upload the repo.** Unzip this and push/upload the contents as a new
   GitHub repository (any name, public or private both work).
2. **Enable GitHub Pages.**
   Repo → Settings → Pages → under "Build and deployment", set
   **Source: Deploy from a branch**, **Branch: main**, folder **/docs** →
   Save. GitHub will give you a URL like
   `https://<you>.github.io/<repo>/` within a minute or two.
3. **Make sure Actions is enabled.**
   Repo → Settings → Actions → General → Actions permissions →
   "Allow all actions and reusable workflows" (this is the default for
   new repos, so usually nothing to do).
4. **Give the workflow permission to push.**
   Repo → Settings → Actions → General → Workflow permissions →
   select **"Read and write permissions"** → Save. (Without this, the
   final "commit and push" step of the daily job will fail with a
   permissions error.)
5. **Run it once by hand** instead of waiting for the schedule:
   Repo → Actions tab → "Daily NFL Prop Predictions" → **Run workflow**.
   Check the run's logs; the first run will fetch two seasons of data and
   can take a couple of minutes.
6. After that first successful run, `docs/index.html` will have real
   projections and your Pages URL will show them. From then on it
   refreshes automatically every day at 13:00 UTC (9am ET) — edit the
   `cron:` line in `.github/workflows/daily.yml` if you want a different
   time.

## Repo layout

```
.github/workflows/daily.yml   the daily automation
scripts/
  common.py                   shared constants/helpers
  fetch_data.py                pulls nflverse data (the only network call)
  build_predictions.py         builds the projections
  generate_site.py             renders docs/index.html
data/                          raw + generated JSON (committed so history builds over time)
docs/                          the static site GitHub Pages serves
requirements.txt
```

## Running it yourself locally (optional)

```bash
pip install -r requirements.txt
cd scripts
python fetch_data.py
python build_predictions.py
python generate_site.py
open ../docs/index.html   # or just open the file in a browser
```

## Ideas for later, if you want to extend it

- **Real sportsbook lines / edge calculation:** sign up for an odds API
  (e.g. The Odds API) and add a `fetch_odds.py` step that pulls current
  player-prop lines, storing the key as a GitHub Actions secret
  (`Settings -> Secrets and variables -> Actions`) rather than in code.
  Then compare `projection` vs. the book's line instead of only showing
  a raw number.
- **Injury / status filtering:** nflverse also publishes injury reports;
  cross-referencing them would let the pipeline flag or drop players
  who are questionable/out instead of surfacing a stale average.
- **Track accuracy over time:** once actual results come in for a week,
  compare them against that week's saved `predictions_<season>_wk<N>.json`
  and log the error — this is the natural next step if you want to know
  whether the multiplier approach is actually adding anything over a
  plain rolling average.
