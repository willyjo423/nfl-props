"""Pull the latest NFL weekly player stats + schedule from nflverse.

This is the only script that talks to the network. It writes raw data to
data/weekly.parquet and data/schedule.parquet so the rest of the pipeline can
run offline against a consistent snapshot.

Rather than trusting nfl_data_py's built-in download URLs (which are
hardcoded in a specific package version and can go stale if nflverse
renames/reorganizes their release files -- exactly what was happening here),
we ask the GitHub Releases API what files actually exist right now, and pick
the correct one dynamically. This is slower per-run but self-corrects
instead of silently 404ing forever.
"""
import sys

import pandas as pd
import requests

from common import current_season, data_path, ensure_dirs, utcnow_iso, write_json

NFLVERSE_REPO = "nflverse/nflverse-data"
GITHUB_API = "https://api.github.com/repos"


def get_release_assets(tag: str) -> list:
    """List of {"name": ..., "browser_download_url": ...} for a release tag."""
    url = f"{GITHUB_API}/{NFLVERSE_REPO}/releases/tags/{tag}"
    resp = requests.get(url, timeout=30, headers={"Accept": "application/vnd.github+json"})
    resp.raise_for_status()
    return resp.json().get("assets", [])


def find_asset(assets: list, must_contain: list) -> dict:
    """First asset whose filename contains every string in must_contain
    (case-insensitive), preferring .parquet files.
    """
    parquet_assets = [a for a in assets if a["name"].lower().endswith(".parquet")]
    for a in parquet_assets:
        name_lower = a["name"].lower()
        if all(token.lower() in name_lower for token in must_contain):
            return a
    return None


def fetch_weekly_safely(years):
    """Fetch weekly player stats straight from nflverse's GitHub release,
    discovering the real current filenames instead of guessing. Tries a
    per-season file first (e.g. containing both "week" and the year), then
    falls back to a single combined file covering all seasons if that's how
    nflverse is currently publishing it.
    """
    try:
        assets = get_release_assets("player_stats")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not list nflverse player_stats release assets: {exc}")

    frames = []
    used_years = []
    remaining_years = list(years)

    # Strategy 1: one file per season, named like "player_stats_2025.parquet"
    for year in list(remaining_years):
        asset = find_asset(assets, [f"player_stats_{year}"])
        if asset is None:
            continue
        try:
            frame = pd.read_parquet(asset["browser_download_url"])
            frames.append(frame)
            used_years.append(year)
            remaining_years.remove(year)
            print(f"  -> season {year}: loaded {asset['name']} ({len(frame)} rows)")
        except Exception as exc:  # noqa: BLE001
            print(f"  -> season {year}: found {asset['name']} but failed to read it ({exc})")

    # Strategy 2: the single combined file (all seasons, weekly grain) that
    # nflverse also publishes as plain "player_stats.parquet" -- used if a
    # per-season file wasn't found for one of the requested years.
    if remaining_years:
        combined = next((a for a in assets if a["name"].lower() == "player_stats.parquet"), None)
        if combined is not None:
            try:
                frame = pd.read_parquet(combined["browser_download_url"])
                if "season" in frame.columns:
                    frame = frame[frame["season"].isin(remaining_years)]
                got_years = sorted(frame["season"].unique().tolist()) if "season" in frame.columns else remaining_years
                if len(frame) > 0:
                    frames.append(frame)
                    used_years.extend(got_years)
                    print(f"  -> combined file {combined['name']}: {len(frame)} rows covering {got_years}")
            except Exception as exc:  # noqa: BLE001
                print(f"  -> combined file {combined['name']} failed to read ({exc})")

    for year in years:
        if year not in used_years:
            print(f"  -> season {year}: no usable data found (may not be published yet); skipping")

    if not frames:
        available = ", ".join(sorted(a["name"] for a in assets if a["name"].lower().endswith(".parquet")))[:500]
        raise RuntimeError(
            "No weekly data could be loaded for any requested season. "
            f"Assets actually available in the player_stats release: {available}"
        )
    return pd.concat(frames, ignore_index=True), sorted(set(used_years))


def fetch_schedule_safely(years) -> pd.DataFrame:
    """Schedule/game data, preferring a direct nflverse release lookup (same
    self-correcting approach as weekly stats) and falling back to
    nfl_data_py's built-in fetch if that release layout can't be found.
    """
    try:
        assets = get_release_assets("schedules")
        combined = find_asset(assets, ["sched"]) or find_asset(assets, ["game"])
        if combined is not None:
            frame = pd.read_parquet(combined["browser_download_url"])
            if "season" in frame.columns:
                frame = frame[frame["season"].isin(years)]
            print(f"  -> loaded {combined['name']} directly ({len(frame)} rows)")
            return frame
        print("  -> no matching asset in nflverse 'schedules' release; falling back to nfl_data_py")
    except Exception as exc:  # noqa: BLE001
        print(f"  -> direct schedule fetch failed ({exc}); falling back to nfl_data_py")

    import nfl_data_py as nfl
    return nfl.import_schedules(years)


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
    schedule = fetch_schedule_safely(years)
    schedule.to_parquet(data_path("schedule.parquet"))
    print(f"  -> {len(schedule)} rows")

    print(f"Fetching injury reports for seasons {years}...")
    try:
        import nfl_data_py as nfl
        injuries = nfl.import_injuries(years)
        injuries.to_parquet(data_path("injuries.parquet"))
        print(f"  -> {len(injuries)} rows")
    except Exception as exc:  # noqa: BLE001 - injury data is a nice-to-have, never block the run over it
        print(f"  -> injury report fetch failed ({exc}); continuing without it")

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
