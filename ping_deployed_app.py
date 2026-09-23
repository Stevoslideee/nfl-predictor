"""Keeps the Streamlit Community Cloud deployment (birdzone.streamlit.app) awake and
pre-warms its cache for the current week, meant to run on a schedule (see the README)
rather than depend on a human visiting first and eating the cold start.

A plain HTTP ping would keep the process alive but wouldn't warm anything week-specific -
Streamlit's @st.cache_data caches are tied to actual function calls with actual
arguments, and get_elo_state_cached(season, week) / get_weekly_hist_cached(season, week)
only run when something (a real click, or this script) asks for that exact season/week.
Loading the bare page only warms get_history() (the slow initial NFL-data fetch) - the
biggest win, but not the current week's Elo/weekly-history state real visitors will hit.
So this drives the real UI like a visitor would: opens the Weekly Report tab, sets the
current season/week (same source of truth daily_update.py uses - live.get_scoreboard),
and clicks "Run weekly report" - which warms the shared caches EVERY game in that week's
slate benefits from, not just one matchup.

The deployed app's cache is a separate, ephemeral process from anything local - this
doesn't sync or duplicate the local predictions/ log, it just keeps the live site fast.
"""

import datetime as dt
from pathlib import Path

from playwright.sync_api import sync_playwright

import live

APP_URL = "https://birdzone.streamlit.app"
LOG_FILE = Path(__file__).parent / "predictions" / "ping_deployed_app.log"


def _log(f, message: str) -> None:
    f.write(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {message}\n")


def _find_app_frame(page):
    """Streamlit Community Cloud wraps the app in an iframe at a "~/+/" path - not just
    any non-main frame, since there's also an unrelated statuspage.io status-widget
    frame on the same page."""
    for f in page.frames:
        if "streamlit.app" in f.url and "~/+/" in f.url:
            return f
    return None


def run(f) -> None:
    scoreboard = live.get_scoreboard(week=None, season=None)
    season, week = scoreboard.get("season"), scoreboard.get("week")
    if not season or not week:
        _log(f, "Couldn't determine the current season/week - pinging the bare page only.")
        season = week = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(APP_URL, timeout=60000)
            page.wait_for_timeout(8000)  # cold start can take a while

            app_frame = _find_app_frame(page)
            if app_frame is None:
                _log(f, "Couldn't find the app's iframe - site may still be waking up. Bare page load still warmed get_history().")
                return

            if season is None:
                _log(f, "Pinged the bare page (no specific week to warm).")
                return

            app_frame.get_by_role("tab", name="Weekly Report").click()
            app_frame.wait_for_timeout(1500)

            panel = app_frame.locator('[role="tabpanel"]:visible')
            panel.get_by_label("Season", exact=True).fill(str(season))
            panel.get_by_label("Week", exact=True).fill(str(week))
            panel.get_by_role("button", name="Run weekly report").click()

            # the report can take a while the first time (cold Elo/weekly-history cache)
            app_frame.get_by_text("Attack notes are each team's own recent-form leaders").wait_for(timeout=90000)
            _log(f, f"Warmed season {season} week {week} successfully.")
        except Exception as e:
            _log(f, f"Ping/warm failed: {e.__class__.__name__}: {e}")
        finally:
            browser.close()


def main():
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        run(f)


if __name__ == "__main__":
    main()
