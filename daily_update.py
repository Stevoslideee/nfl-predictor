"""Meant to run once a day, unattended (see the Windows Scheduled Task set up alongside
this file) - logs fresh predictions for the current week's real games and re-grades
anything that's finished, so the live tracking record in the app stays current without
anyone having to remember to open it.

Logging every day, not just once a week, is deliberate: re-running the same game
mid-week captures how the prediction moved as injury news firmed up (each entry is
timestamped and appended, never overwritten - see tracking.log_prediction), which is
useful context tracking.py doesn't otherwise have.

Everything is appended to predictions/daily_run.log instead of printed, since a
scheduled task has no visible console to print to.
"""

import datetime as dt
import traceback
from pathlib import Path

import live
import tracking
from data import load_injuries, load_schedules, load_weekly_player_stats
from predict import elo_state_as_of, prefetch_weather_for_matchups, predict_matchup, weekly_hist_as_of

LOG_FILE = Path(__file__).parent / "predictions" / "daily_run.log"
SEASONS = list(range(2010, dt.date.today().year + 1))


def _log(f, message: str) -> None:
    f.write(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {message}\n")


def run(f) -> None:
    scoreboard = live.get_scoreboard(week=None, season=None)
    season, week = scoreboard.get("season"), scoreboard.get("week")
    if not season or not week:
        _log(f, "Couldn't determine the current season/week from ESPN's scoreboard - skipping today's logging.")
        return

    games = scoreboard["games"]
    _log(f, f"Season {season}, Week {week}: {len(games)} games found.")
    if not games:
        return

    schedules = load_schedules(SEASONS)
    weekly = load_weekly_player_stats(SEASONS)
    injuries = load_injuries([season - 1, season])
    elo_state = elo_state_as_of(schedules, season, week)
    weekly_hist = weekly_hist_as_of(weekly, season, week)

    matchups = [(g["home_team"], g["away_team"]) for g in games]
    prefetch_weather_for_matchups(schedules, matchups, season, week)

    logged = 0
    for g in games:
        home, away = g["home_team"], g["away_team"]
        try:
            pred = predict_matchup(
                schedules, weekly, home, away, season, week,
                injuries=injuries, elo_state=elo_state, weekly_hist=weekly_hist,
            )
            tracking.log_prediction(pred, season, week)
            logged += 1
        except Exception as e:
            _log(f, f"  Failed to predict/log {away} @ {home}: {e.__class__.__name__}: {e}")
    _log(f, f"Logged {logged}/{len(games)} predictions for week {week}.")

    graded = tracking.grade_log(schedules, weekly)
    summary = tracking.summarize(graded)
    if summary:
        _log(
            f,
            f"Running tally: {summary['games']} graded games, "
            f"winner accuracy {summary['accuracy']:.1%}, Brier {summary['brier']:.4f}"
            + (
                f", personnel-assumption accuracy {summary['personnel_assumption_accuracy']:.1%}"
                if summary["personnel_assumption_accuracy"] is not None else ""
            ),
        )


def main():
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        try:
            run(f)
        except Exception:
            _log(f, "Daily update crashed:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
