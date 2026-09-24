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


WAKE_BUTTON_TEXT = "Yes, get this app back up!"

# After enough inactivity, Community Cloud puts the app to sleep entirely - visiting it
# then shows a top-level "Zzzz... this app has gone to sleep" splash with a wake-up
# button, not the app's iframe at all. A fixed short wait before giving up on the iframe
# (the previous approach) fails every single time against a genuinely sleeping app, since
# there's no iframe to find until that button is clicked and the container boots back up
# (which, combined with this app's own cold-start data load, can take well over a minute)
# - this is exactly the failure mode that showed up repeatedly in the log.
WAKE_TIMEOUT_MS = 20_000
FRAME_POLL_TIMEOUT_MS = 120_000
FRAME_POLL_INTERVAL_MS = 3_000


def _wake_if_sleeping(page, f) -> None:
    try:
        button = page.get_by_role("button", name=WAKE_BUTTON_TEXT)
        button.wait_for(state="visible", timeout=WAKE_TIMEOUT_MS)
    except Exception:
        return  # app wasn't asleep (or the splash didn't appear in time) - nothing to do
    _log(f, "App was asleep - clicking to wake it back up.")
    button.click()


def _wait_for_app_frame(page, total_timeout_ms: int = FRAME_POLL_TIMEOUT_MS):
    """Polls for the app's iframe instead of a single fixed sleep - a real cold start
    (Community Cloud's own container boot, on top of this app's "Loading NFL history"
    step) has taken 30+ seconds even after clicking the wake-up button, well past what a
    one-shot short wait can cover."""
    elapsed = 0
    while elapsed < total_timeout_ms:
        frame = _find_app_frame(page)
        if frame is not None:
            return frame
        page.wait_for_timeout(FRAME_POLL_INTERVAL_MS)
        elapsed += FRAME_POLL_INTERVAL_MS
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
            _wake_if_sleeping(page, f)

            app_frame = _wait_for_app_frame(page)
            if app_frame is None:
                _log(f, "Couldn't find the app's iframe even after waiting - site may be having a real issue. Bare page load still warmed get_history().")
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
