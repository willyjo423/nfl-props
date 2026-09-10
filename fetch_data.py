"""Pull the latest NFL weekly player stats + schedule from nflverse.

This is the only script that talks to the network. It writes raw data to
data/weekly.parquet and data/schedule.parquet so the rest of the pipeline can
run offline against a consistent snapshot.
"""
import sys

import nfl_data_py as nfl

from common import current_season, data_path, ensure_dirs, utcnow_iso, write_json


def main():
    ensure_dirs()
    season = current_season()
    # Pull the current season plus the prior one so early-season rookies /
    # small samples still have *some* history to fall back on.
    years = [season - 1, season]

    print(f"Fetching weekly player data for seasons {years}...")
    weekly = nfl.import_weekly_data(years, downcast=True)
    weekly.to_parquet(data_path("weekly.parquet"))
    print(f"  -> {len(weekly)} rows")

    print(f"Fetching schedules for seasons {years}...")
    schedule = nfl.import_schedules(years)
    schedule.to_parquet(data_path("schedule.parquet"))
    print(f"  -> {len(schedule)} rows")

    write_json(
        data_path("fetch_meta.json"),
        {"season": season, "years": years, "fetched_at": utcnow_iso()},
    )
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface a clean failure to Actions logs
        print(f"fetch_data.py failed: {exc}", file=sys.stderr)
        raise
