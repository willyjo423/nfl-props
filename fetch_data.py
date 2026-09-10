"""Pull the latest NFL weekly player stats + schedule from nflverse.

This is the only script that talks to the network. It writes raw data to
data/weekly.parquet and data/schedule.parquet so the rest of the pipeline can
run offline against a consistent snapshot.
"""
import sys

import pandas as pd
import nfl_data_py as nfl

from common import current_season, data_path, ensure_dirs, utcnow_iso, write_json


def fetch_weekly_safely(years):
    """Fetch weekly data year by year, skipping any year nflverse hasn't
    published yet (e.g. very early in a new season, before the first
    weekly-stats file for that season exists -- this shows up as an
    HTTP 404 from the underlying parquet fetch).
    """
    frames = []
    used_years = []
    for year in years:
        try:
            frame = nfl.import_weekly_data([year], downcast=True)
            frames.append(frame)
            used_years.append(year)
            print(f"  -> season {year}: {len(frame)} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"  -> season {year}: not available yet ({exc}); skipping")
    if not frames:
        raise RuntimeError(
            "No weekly data available for any requested season -- "
            "nflverse may not have published anything yet."
        )
    return pd.concat(frames, ignore_index=True), used_years


def main():
    ensure_dirs()
    season = current_season()
    # Pull the current season plus the prior one so early-season rookies /
    # small samples still have *some* history to fall back on.
    years = [season - 1, season]

    print(f"Fetching weekly player data for seasons {years}...")
    weekly, used_years = fetch_weekly_safely(years)
    weekly.to_parquet(data_path("weekly.parquet"))
    print(f"Total weekly rows: {len(weekly)} (seasons actually used: {used_years})")

    print(f"Fetching schedules for seasons {years}...")
    schedule = nfl.import_schedules(years)
    schedule.to_parquet(data_path("schedule.parquet"))
    print(f"  -> {len(schedule)} rows")

    write_json(
        data_path("fetch_meta.json"),
        {
            "season": season,
            "years_requested": years,
            "years_used_for_weekly": used_years,
            "fetched_at": utcnow_iso(),
        },
    )
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface a clean failure to Actions logs
        print(f"fetch_data.py failed: {exc}", file=sys.stderr)
        raise
