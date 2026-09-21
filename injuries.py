"""Official weekly NFL injury report lookups, used for context (not a numeric
adjustment to the model - injury impact varies too much by player/scheme to
guess at honestly, so this is surfaced as information for you to weigh yourself).
"""

import pandas as pd

import player_stats

CONCERNING_STATUSES = ("Out", "Doubtful", "Questionable")


def team_injury_report(injuries: pd.DataFrame, team: str, season: int, week: int) -> pd.DataFrame:
    """The most recently published injury report for this team at or before the given week."""
    team_rows = injuries[(injuries["team"] == team) & (injuries["season"] == season) & (injuries["week"] <= week)]
    if team_rows.empty:
        return team_rows

    latest_week = team_rows["week"].max()
    report = team_rows[team_rows["week"] == latest_week]
    report = report[report["report_status"].isin(CONCERNING_STATUSES)]
    cols = ["full_name", "position", "report_primary_injury", "report_status"]
    return report[cols].sort_values("report_status").reset_index(drop=True)


def starting_qb_status(report: pd.DataFrame, qb_name: str | None) -> str | None:
    """Injury designation for the given nflverse-format QB name ('P.Mahomes'), if listed
    in `report` (the output of team_injury_report - pass the same one you already
    computed for display, rather than a fresh call, since they're the same lookup)."""
    if report.empty or qb_name is None:
        return None
    for row in report.itertuples():
        if player_stats.espn_name_to_nflverse(row.full_name) == qb_name:
            return row.report_status
    return None
