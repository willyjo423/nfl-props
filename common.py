"""Shared helpers for the NFL prop predictor pipeline."""
import datetime as dt
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

POSITIONS = ["QB", "RB", "WR", "TE"]

# Stats we project for each position. Keys are the nfl_data_py weekly column
# names; values are the human-readable label used in the site + JSON output.
POSITION_STATS = {
    "QB": {
        "passing_yards": "Passing Yards",
        "passing_tds": "Passing TDs",
        "interceptions": "Interceptions",
        "rushing_yards": "Rushing Yards",
    },
    "RB": {
        "rushing_yards": "Rushing Yards",
        "rushing_tds": "Rushing TDs",
        "receptions": "Receptions",
        "receiving_yards": "Receiving Yards",
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
