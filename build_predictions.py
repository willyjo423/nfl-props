"""Turn the raw nflverse snapshot into next-week player prop projections.

Method (deliberately simple and inspectable, not a black box):
  1. For every player, take a recency-weighted average of their own last
     4 games at each relevant stat ("their own baseline").
  2. For every defense, work out how many of that stat opposing players at
     that position have averaged against them over their last 4 games,
     expressed as a multiplier vs. the league average ("matchup adjustment").
  3. Projection = baseline * matchup adjustment, clipped to +/-25% so one
     small sample game can't blow up the number.

This is a statistical starting point for your own research, not a finished
edge. It does not know about injuries, weather, depth-chart changes, or
sportsbook lines -- see the README for what it does and doesn't account for.
"""
import sys

import numpy as np
import pandas as pd

from common import (
    POSITION_STATS,
    POSITIONS,
    compute_fantasy_points,
    current_season,
    data_path,
    ensure_dirs,
    read_json,
    utcnow_iso,
    write_json,
)
import os

RECENCY_WEIGHTS = [0.40, 0.28, 0.20, 0.12]  # most recent game first
LOOKBACK_GAMES = len(RECENCY_WEIGHTS)
MIN_GAMES_FOR_PROJECTION = 2
MULTIPLIER_BOUNDS = (0.75, 1.25)
MIN_TOUCHES_BY_POS = {
    # minimum recent-average "touches" (attempts/carries/targets) to be
    # considered a real weekly option at that position, to keep 3rd-string
    # players out of the table.
    "QB": {"col": "attempts", "min": 8},
    "RB": {"col": "carries", "min": 3},
    "WR": {"col": "targets", "min": 2},
    "TE": {"col": "targets", "min": 2},
}
TOP_N_BY_POS = {"QB": 1, "RB": 3, "WR": 5, "TE": 3}


def weighted_avg(values: pd.Series) -> float:
    """Weighted average of a player's most recent games, most-recent first.

    `values` is expected already sorted most-recent-first and truncated to
    LOOKBACK_GAMES. Falls back to a straight mean if fewer games exist.
    """
    n = len(values)
    if n == 0:
        return np.nan
    weights = RECENCY_WEIGHTS[:n]
    weights = np.array(weights) / sum(weights)
    return float(np.dot(values.to_numpy(), weights))


def build_player_baselines(weekly: pd.DataFrame) -> pd.DataFrame:
    """One row per player: recent-form averages for every tracked stat."""
    weekly = weekly[weekly["position"].isin(POSITIONS)].copy()
    weekly = weekly[weekly["season_type"] == "REG"]
    weekly = weekly.sort_values(["player_id", "season", "week"], ascending=[True, False, False])

    all_stat_cols = sorted({c for stats in POSITION_STATS.values() for c in stats})
    touch_cols = {v["col"] for v in MIN_TOUCHES_BY_POS.values()}
    needed_cols = set(all_stat_cols) | touch_cols

    rows = []
    for player_id, grp in weekly.groupby("player_id", sort=False):
        grp = grp.head(LOOKBACK_GAMES)
        if len(grp) < MIN_GAMES_FOR_PROJECTION:
            continue
        latest = grp.iloc[0]
        position = latest["position"]
        if position not in POSITIONS:
            continue
        row = {
            "player_id": player_id,
            "player_name": latest.get("player_display_name", latest.get("player_name")),
            "position": position,
            "team": latest.get("recent_team"),
            "games_sampled": len(grp),
        }
        for col in needed_cols:
            if col in grp.columns:
                row[f"avg_{col}"] = weighted_avg(grp[col].fillna(0))
        rows.append(row)

    return pd.DataFrame(rows)


def build_defense_factors(weekly: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """Per-defense, per-position, per-stat multiplier vs. league average.

    Built from how much opposing offenses have put up against each team
    over their last 4 games (weighted the same way as player baselines).
    """
    sched = schedule[["season", "week", "home_team", "away_team"]].drop_duplicates()
    weekly = weekly.merge(sched, on=["season", "week"], how="left")
    weekly["opponent"] = np.where(
        weekly["recent_team"] == weekly["home_team"],
        weekly["away_team"],
        weekly["home_team"],
    )
    weekly = weekly[weekly["position"].isin(POSITIONS)]
    weekly = weekly[weekly["season_type"] == "REG"]

    all_stat_cols = sorted({c for stats in POSITION_STATS.values() for c in stats})
    # sum each defense's allowed stats per game per position, then take the
    # recency-weighted average of the last 4 games played, then compare to
    # league average for that position/stat.
    grouped = (
        weekly.groupby(["opponent", "position", "season", "week"])[all_stat_cols]
        .sum()
        .reset_index()
        .sort_values(["opponent", "position", "season", "week"], ascending=[True, True, False, False])
    )

    factor_rows = []
    for position in POSITIONS:
        pos_grp = grouped[grouped["position"] == position]
        stat_cols = list(POSITION_STATS[position].keys())
        # league average per game for this position/stat (all teams, all weeks sampled)
        league_avg_vals = pos_grp[stat_cols].mean()

        for opponent, team_grp in pos_grp.groupby("opponent"):
            team_grp = team_grp.head(LOOKBACK_GAMES)
            if len(team_grp) == 0:
                continue
            row = {"team": opponent, "position": position}
            for stat in stat_cols:
                allowed = weighted_avg(team_grp[stat].fillna(0))
                league_val = league_avg_vals.get(stat, np.nan)
                if not league_val or np.isnan(league_val) or league_val == 0:
                    mult = 1.0
                else:
                    mult = allowed / league_val
                mult = float(np.clip(mult, *MULTIPLIER_BOUNDS))
                row[f"mult_{stat}"] = mult
                row[f"allowed_{stat}"] = allowed
            factor_rows.append(row)

    return pd.DataFrame(factor_rows)


def load_injury_lookup(season: int, target_week: int) -> dict:
    """gsis player_id -> latest known report status ('Questionable',
    'Doubtful', 'Out', etc.) for the target week, if injury data was
    fetched successfully. Returns {} if unavailable -- this is a bonus
    signal, never a hard dependency.
    """
    path = data_path("injuries.parquet")
    if not os.path.exists(path):
        return {}
    try:
        inj = pd.read_parquet(path)
    except Exception:  # noqa: BLE001
        return {}

    id_col = "gsis_id" if "gsis_id" in inj.columns else ("player_id" if "player_id" in inj.columns else None)
    status_col = "report_status" if "report_status" in inj.columns else None
    if id_col is None or status_col is None or "week" not in inj.columns or "season" not in inj.columns:
        return {}

    # most recent report at or before the target week for this season
    sub = inj[(inj["season"] == season) & (inj["week"] <= target_week)]
    if sub.empty:
        return {}
    sub = sub.sort_values("week", ascending=False)
    sub = sub.dropna(subset=[status_col])
    sub = sub.drop_duplicates(subset=[id_col], keep="first")
    return dict(zip(sub[id_col], sub[status_col]))


def find_target_week(schedule: pd.DataFrame, season: int):
    """Pick the next week in `season` that hasn't been fully played yet."""
    season_games = schedule[schedule["season"] == season].copy()
    if season_games.empty:
        return None, pd.DataFrame()

    if "result" in season_games.columns:
        unplayed = season_games[season_games["result"].isna()]
    else:
        unplayed = season_games[season_games["home_score"].isna()]

    if unplayed.empty:
        return None, pd.DataFrame()

    target_week = int(unplayed["week"].min())
    games = season_games[season_games["week"] == target_week]
    return target_week, games


def main():
    ensure_dirs()
    meta = read_json(data_path("fetch_meta.json"))
    season = meta["season"]

    weekly = pd.read_parquet(data_path("weekly.parquet"))
    schedule = pd.read_parquet(data_path("schedule.parquet"))

    target_week, games = find_target_week(schedule, season)
    if target_week is None:
        print("No upcoming games found for the current season (offseason?). Writing empty predictions.")
        write_json(
            data_path("predictions_latest.json"),
            {
                "season": season,
                "week": None,
                "generated_at": utcnow_iso(),
                "games": [],
                "predictions": [],
                "note": "No unplayed games found for this season yet -- likely offseason.",
            },
        )
        return

    print(f"Projecting season {season}, week {target_week} ({len(games)} games).")

    baselines = build_player_baselines(weekly)
    defense = build_defense_factors(weekly, schedule)

    # map team -> opponent for the target week
    team_opponent = {}
    game_list = []
    for _, g in games.iterrows():
        team_opponent[g["home_team"]] = g["away_team"]
        team_opponent[g["away_team"]] = g["home_team"]
        game_list.append(
            {
                "home_team": g["home_team"],
                "away_team": g["away_team"],
                "gameday": g.get("gameday"),
            }
        )

    playing_teams = set(team_opponent.keys())
    baselines = baselines[baselines["team"].isin(playing_teams)].copy()

    injury_lookup = load_injury_lookup(season, target_week)

    predictions = []
    for position in POSITIONS:
        pos_players = baselines[baselines["position"] == position].copy()
        touch_rule = MIN_TOUCHES_BY_POS[position]
        touch_col = f"avg_{touch_rule['col']}"
        if touch_col in pos_players.columns:
            pos_players = pos_players[pos_players[touch_col].fillna(0) >= touch_rule["min"]]

        # rank by usage within each team so we only surface the real options
        sort_col = touch_col if touch_col in pos_players.columns else None
        if sort_col:
            pos_players = pos_players.sort_values(sort_col, ascending=False)

        top_n = TOP_N_BY_POS[position]
        pos_players = pos_players.groupby("team", group_keys=False).head(top_n)

        pos_defense = defense[defense["position"] == position].set_index("team")

        for _, player in pos_players.iterrows():
            team = player["team"]
            opponent = team_opponent.get(team)
            if opponent is None:
                continue
            def_row = pos_defense.loc[opponent] if opponent in pos_defense.index else None

            stat_predictions = {}
            proj_by_col = {}
            for stat_col, label in POSITION_STATS[position].items():
                baseline = player.get(f"avg_{stat_col}")
                if baseline is None or pd.isna(baseline):
                    continue
                mult = 1.0
                if def_row is not None:
                    mult = def_row.get(f"mult_{stat_col}", 1.0)
                    if pd.isna(mult):
                        mult = 1.0
                projection = round(baseline * mult, 1)
                stat_predictions[label] = {
                    "projection": projection,
                    "recent_avg": round(float(baseline), 1),
                    "matchup_multiplier": round(float(mult), 2),
                }
                proj_by_col[stat_col] = projection

            if not stat_predictions:
                continue

            predictions.append(
                {
                    "player": player["player_name"],
                    "position": position,
                    "team": team,
                    "opponent": opponent,
                    "games_sampled": int(player["games_sampled"]),
                    "stats": stat_predictions,
                    "fantasy_points": compute_fantasy_points(proj_by_col),
                    "injury_status": injury_lookup.get(player.get("player_id")),
                }
            )

    output = {
        "season": season,
        "week": target_week,
        "generated_at": utcnow_iso(),
        "games": game_list,
        "predictions": predictions,
    }
    write_json(data_path("predictions_latest.json"), output)
    write_json(data_path(f"predictions_{season}_wk{target_week}.json"), output)
    print(f"Wrote {len(predictions)} player projections.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"build_predictions.py failed: {exc}", file=sys.stderr)
        raise
