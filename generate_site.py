"""Render data/predictions_latest.json into a static docs/index.html page."""
import sys

from common import POSITIONS, data_path, docs_path, ensure_dirs, read_json

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL Prop Projections</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 1200px; margin: 0 auto; padding: 24px 16px; background: #0f1115; color: #e7e9ee; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
  .meta {{ color: #9aa1ac; font-size: 0.9rem; margin-bottom: 24px; }}
  .disclaimer {{ background: #1b1e26; border: 1px solid #2a2e38; border-radius: 8px; padding: 12px 16px; font-size: 0.85rem; color: #b7bcc7; margin-bottom: 28px; }}
  h2 {{ border-bottom: 2px solid #2a2e38; padding-bottom: 6px; margin-top: 36px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #22252d; white-space: nowrap; }}
  th {{ color: #9aa1ac; font-weight: 600; }}
  tr:hover {{ background: #171a21; }}
  .proj {{ font-weight: 700; }}
  .mult-up {{ color: #7bd88f; }}
  .mult-down {{ color: #e57373; }}
  .empty {{ color: #9aa1ac; padding: 24px 0; }}
  .fp {{ font-weight: 700; color: #7fb3ff; }}
  .fp-row {{ font-size: 0.82rem; color: #b7bcc7; }}
  .badge {{ display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 0.72rem; font-weight: 700; margin-left: 6px; }}
  .badge-out {{ background: #4a1f1f; color: #ff8a8a; }}
  .badge-doubtful {{ background: #4a331f; color: #ffbd7a; }}
  .badge-questionable {{ background: #4a441f; color: #ffe27a; }}
  .table-wrap {{ overflow-x: auto; }}
</style>
</head>
<body>
  <h1>NFL Prop Projections</h1>
  <div class="meta">{meta_line}</div>
  <div class="disclaimer">
    Statistical projections only: a recency-weighted average of each player's
    last few games, adjusted by how that opponent has performed against the
    position recently. Depth-chart news, weather, and sportsbook lines are
    not factored in. Injury tags reflect the most recent official report
    nflverse has published, when available. Fantasy points are calculated
    from the stat projections using each site's public scoring rules, not
    pulled from the sites themselves. Treat this as a research starting
    point, not a finished pick.
  </div>
  {body}
</body>
</html>
"""

POSITION_SECTION = """
  <h2>{position}</h2>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Player</th><th>Team</th><th>Opp</th>{stat_headers}<th>DK pts</th><th>FD pts</th><th>Std / PPR</th><th>Sample</th></tr></thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  </div>
"""

INJURY_BADGE_CLASS = {
    "Out": "badge-out",
    "Doubtful": "badge-doubtful",
    "Questionable": "badge-questionable",
}


def render_multiplier(mult: float) -> str:
    cls = "mult-up" if mult > 1.02 else ("mult-down" if mult < 0.98 else "")
    return f'<span class="{cls}">{mult:.2f}x</span>'


def render_injury_badge(status) -> str:
    if not status:
        return ""
    cls = INJURY_BADGE_CLASS.get(status, "badge-questionable")
    return f'<span class="badge {cls}">{status}</span>'


def render_position_section(position: str, players: list) -> str:
    if not players:
        return ""
    # Union of stat labels present for this position, in a stable order
    stat_labels = []
    for p in players:
        for label in p["stats"]:
            if label not in stat_labels:
                stat_labels.append(label)

    stat_headers = "".join(f"<th>{label}</th>" for label in stat_labels)

    rows = []
    for p in players:
        cells = [
            f"<td>{p['player']}{render_injury_badge(p.get('injury_status'))}</td>",
            f"<td>{p['team']}</td>",
            f"<td>@{p['opponent']}</td>",
        ]
        for label in stat_labels:
            s = p["stats"].get(label)
            if not s:
                cells.append("<td>-</td>")
                continue
            cells.append(
                f"<td><span class='proj'>{s['projection']}</span> "
                f"<small>({s['recent_avg']} avg, {render_multiplier(s['matchup_multiplier'])})</small></td>"
            )
        fp = p.get("fantasy_points", {})
        cells.append(f"<td><span class='fp'>{fp.get('draftkings', '-')}</span></td>")
        cells.append(f"<td><span class='fp'>{fp.get('fanduel', '-')}</span></td>")
        cells.append(f"<td class='fp-row'>{fp.get('standard', '-')} / {fp.get('ppr', '-')}</td>")
        cells.append(f"<td>{p['games_sampled']}g</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return POSITION_SECTION.format(position=position, stat_headers=stat_headers, rows="\n      ".join(rows))


def main():
    ensure_dirs()
    payload = read_json(data_path("predictions_latest.json"))

    if not payload.get("predictions"):
        meta_line = payload.get("note", "No predictions available yet.")
        html = PAGE_TEMPLATE.format(meta_line=meta_line, body="<p class='empty'>Check back once the season is underway.</p>")
    else:
        meta_line = (
            f"Season {payload['season']}, Week {payload['week']} &mdash; "
            f"generated {payload['generated_at']}"
        )
        by_position = {pos: [] for pos in POSITIONS}
        for p in payload["predictions"]:
            by_position.setdefault(p["position"], []).append(p)

        body = "".join(render_position_section(pos, by_position.get(pos, [])) for pos in POSITIONS)
        html = PAGE_TEMPLATE.format(meta_line=meta_line, body=body)

    with open(docs_path("index.html"), "w") as f:
        f.write(html)
    print("Wrote docs/index.html")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"generate_site.py failed: {exc}", file=sys.stderr)
        raise
