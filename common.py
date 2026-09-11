"""Shared helpers for the NFL prop predictor pipeline."""
import datetime as dt
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")

POSITIONS = ["QB", "RB", "WR", "TE"]

# Stats we project for each position. Keys are the nfl_data_py weekly column
# names; values are the human-readable label used in the site + JSON output.
POSITION_STATS = {
    "QB": {
        "passing_yards": "Passing Yards",
        "passing_tds": "Passing TDs",
        "interceptions": "Interceptions",
        "rushing_yards": "Rushing Yards",
        "rushing_tds": "Rushing TDs",
    },
    "RB": {
        "rushing_yards": "Rushing Yards",
        "rushing_tds": "Rushing TDs",
        "receptions": "Receptions",
        "receiving_yards": "Receiving Yards",
        "receiving_tds": "Receiving TDs",
    },
    "WR": {
        "receptions": "Receptions",
        "receiving_yards": "Receiving Yards",
        "receiving_tds": "Receiving TDs",
        "targets": "Targets",
    },
    "TE": {
        "receptions": "Receptions",
        "receiving_yards": "Receiving Yards",
        "receiving_tds": "Receiving TDs",
        "targets": "Targets",
    },
}

# Public DFS scoring rules (offense). Sources: DraftKings and FanDuel both
# publish these on their own sites; nothing paywalled here. "standard" and
# "ppr"/"half_ppr" are the common non-site-specific fantasy formats.
# Format: pass_yd, pass_td, interception, rush_yd, rush_td, rec, rec_yd, rec_td, then optional bonus thresholds.
FANTASY_SCORING = {
    "draftkings": {
        "pass_yd": 0.04, "pass_td": 4, "interception": -1,
        "rush_yd": 0.1, "rush_td": 6,
        "reception": 1, "rec_yd": 0.1, "rec_td": 6,
        "pass_yd_bonus": (300, 3), "rush_yd_bonus": (100, 3), "rec_yd_bonus": (100, 3),
    },
    "fanduel": {
        "pass_yd": 0.04, "pass_td": 4, "interception": -1,
        "rush_yd": 0.1, "rush_td": 6,
        "reception": 0.5, "rec_yd": 0.1, "rec_td": 6,
    },
    "standard": {
        "pass_yd": 0.04, "pass_td": 4, "interception": -1,
        "rush_yd": 0.1, "rush_td": 6,
        "reception": 0, "rec_yd": 0.1, "rec_td": 6,
    },
    "ppr": {
        "pass_yd": 0.04, "pass_td": 4, "interception": -1,
        "rush_yd": 0.1, "rush_td": 6,
        "reception": 1, "rec_yd": 0.1, "rec_td": 6,
    },
}


def compute_fantasy_points(proj_by_col: dict) -> dict:
    """proj_by_col: raw nflverse column name -> projected value (0 if absent).
    Returns {"draftkings": x, "fanduel": x, "standard": x, "ppr": x}, each
    rounded to 1 decimal.
    """
    def g(col):
        v = proj_by_col.get(col)
        return float(v) if v is not None else 0.0

    pass_yd, pass_td, ints = g("passing_yards"), g("passing_tds"), g("interceptions")
    rush_yd, rush_td = g("rushing_yards"), g("rushing_tds")
    rec, rec_yd, rec_td = g("receptions"), g("receiving_yards"), g("receiving_tds")

    out = {}
    for site, r in FANTASY_SCORING.items():
        pts = (
            pass_yd * r["pass_yd"] + pass_td * r["pass_td"] + ints * r["interception"]
            + rush_yd * r["rush_yd"] + rush_td * r["rush_td"]
            + rec * r["reception"] + rec_yd * r["rec_yd"] + rec_td * r["rec_td"]
        )
        if "pass_yd_bonus" in r and pass_yd >= r["pass_yd_bonus"][0]:
            pts += r["pass_yd_bonus"][1]
        if "rush_yd_bonus" in r and rush_yd >= r["rush_yd_bonus"][0]:
            pts += r["rush_yd_bonus"][1]
        if "rec_yd_bonus" in r and rec_yd >= r["rec_yd_bonus"][0]:
            pts += r["rec_yd_bonus"][1]
        out[site] = round(pts, 1)
    return out


def current_season(today: dt.date = None) -> int:
    """Best-guess NFL season label for 'today'.

    The NFL league year / season is named after the year it kicks off in
    (e.g. games played in Jan/Feb 2027 belong to the "2026 season"). We treat
    January and February as still belonging to the previous September's
    season; every other month maps to its own calendar year.
    """
    today = today or dt.date.today()
    if today.month in (1, 2):
        return today.year - 1
    return today.year


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)


def data_path(*parts) -> str:
    return os.path.join(DATA_DIR, *parts)


def docs_path(*parts) -> str:
    return os.path.join(DOCS_DIR, *parts)


def write_json(path: str, payload) -> None:
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)


def read_json(path: str):
    with open(path) as f:
        return json.load(f)


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
