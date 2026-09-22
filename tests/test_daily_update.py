"""daily_update.py is the unattended entry point behind the Windows Scheduled Task and
desktop notifications - both verified manually (real toast, real dedup) when built, but
never covered by an automatic test. These tests isolate its notification-trigger logic
(the part most likely to silently regress) from all the real network/data/model calls
`run()` otherwise makes, using fakes for everything external.
"""
import io
import json
import subprocess

import pytest

import daily_update


def _game(home, away):
    return {"home_team": home, "away_team": away}


def _graded_row(home, away, correct=True):
    """Minimal shape tracking.summarize() needs - real keys, fake values."""
    return {
        "season": 2026, "week": 3, "home_team": home, "away_team": away,
        "winner_correct": correct, "home_win_prob": 0.6 if correct else 0.4,
        "actual_winner": home if correct else away,
        "margin_error": 3.0,
        "personnel_checks": {"home_qb": True, "away_qb": False},
        "prop_grades": {"home_qb": "Correct"},
    }


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Replace every external dependency run() touches with a controllable fake, and
    point notification state at a scratch file so tests never touch real predictions/."""
    monkeypatch.setattr(daily_update, "NOTIFIED_WEEKS_PATH", tmp_path / "notified_weeks.json")
    monkeypatch.setattr(daily_update, "load_schedules", lambda seasons: "schedules")
    monkeypatch.setattr(daily_update, "load_weekly_player_stats", lambda seasons: "weekly")
    monkeypatch.setattr(daily_update, "load_injuries", lambda seasons: "injuries")
    monkeypatch.setattr(daily_update, "elo_state_as_of", lambda *a, **k: "elo_state")
    monkeypatch.setattr(daily_update, "weekly_hist_as_of", lambda *a, **k: "weekly_hist")
    monkeypatch.setattr(daily_update, "prefetch_weather_for_matchups", lambda *a, **k: None)
    monkeypatch.setattr(daily_update, "predict_matchup", lambda *a, **k: "pred")
    monkeypatch.setattr(daily_update.tracking, "log_prediction", lambda *a, **k: None)

    sent = []
    monkeypatch.setattr(daily_update, "send_toast", lambda title, message: sent.append((title, message)))
    yield sent


def _set_scoreboard(monkeypatch, season, week, games):
    # the lambda's own params must NOT be named week/season - that would shadow the
    # captured closure values with the caller's None defaults instead of using them
    fake_board = {"season": season, "week": week, "games": games}
    monkeypatch.setattr(daily_update.live, "get_scoreboard", lambda **kwargs: fake_board)


def test_no_season_week_skips_gracefully(monkeypatch, isolated_env):
    monkeypatch.setattr(daily_update.live, "get_scoreboard", lambda week=None, season=None: {"season": None, "week": None, "games": []})
    daily_update.run(io.StringIO())  # must not raise
    assert isolated_env == []  # no notification sent


def test_notifies_once_when_week_fully_graded(monkeypatch, isolated_env):
    games = [_game("AAA", "BBB"), _game("CCC", "DDD")]
    _set_scoreboard(monkeypatch, 2026, 3, games)
    graded = [_graded_row("AAA", "BBB"), _graded_row("CCC", "DDD", correct=False)]
    monkeypatch.setattr(daily_update.tracking, "grade_log", lambda *a, **k: graded)

    daily_update.run(io.StringIO())

    assert len(isolated_env) == 1
    title, message = isolated_env[0]
    assert "Week 3" in title
    assert "2/2 games graded" in message
    assert "50%" in message  # 1 of 2 correct

    saved = json.loads(daily_update.NOTIFIED_WEEKS_PATH.read_text())
    assert saved == [[2026, 3]]


def test_does_not_notify_when_week_only_partially_graded(monkeypatch, isolated_env):
    games = [_game("AAA", "BBB"), _game("CCC", "DDD")]
    _set_scoreboard(monkeypatch, 2026, 3, games)
    graded = [_graded_row("AAA", "BBB")]  # only 1 of 2 games graded so far
    monkeypatch.setattr(daily_update.tracking, "grade_log", lambda *a, **k: graded)

    daily_update.run(io.StringIO())

    assert isolated_env == []
    assert not daily_update.NOTIFIED_WEEKS_PATH.exists()


def test_does_not_renotify_an_already_notified_week(monkeypatch, isolated_env):
    games = [_game("AAA", "BBB")]
    _set_scoreboard(monkeypatch, 2026, 3, games)
    graded = [_graded_row("AAA", "BBB")]
    monkeypatch.setattr(daily_update.tracking, "grade_log", lambda *a, **k: graded)
    daily_update.NOTIFIED_WEEKS_PATH.write_text(json.dumps([[2026, 3]]))

    daily_update.run(io.StringIO())

    assert isolated_env == []  # already notified - must not fire again


def test_failed_notification_is_not_marked_notified_so_it_retries(monkeypatch, isolated_env):
    games = [_game("AAA", "BBB")]
    _set_scoreboard(monkeypatch, 2026, 3, games)
    graded = [_graded_row("AAA", "BBB")]
    monkeypatch.setattr(daily_update.tracking, "grade_log", lambda *a, **k: graded)

    def failing_toast(title, message):
        raise RuntimeError("no display session")

    monkeypatch.setattr(daily_update, "send_toast", failing_toast)

    daily_update.run(io.StringIO())  # must not raise - failure is caught and logged

    assert not daily_update.NOTIFIED_WEEKS_PATH.exists()  # not marked notified - will retry


def test_one_failed_prediction_does_not_stop_the_others(monkeypatch, isolated_env):
    games = [_game("AAA", "BBB"), _game("CCC", "DDD")]
    _set_scoreboard(monkeypatch, 2026, 3, games)
    monkeypatch.setattr(daily_update.tracking, "grade_log", lambda *a, **k: [])

    calls = []

    def flaky_predict(schedules, weekly, home, away, season, week, **kwargs):
        calls.append((home, away))
        if home == "AAA":
            raise ValueError("simulated failure")
        return "pred"

    monkeypatch.setattr(daily_update, "predict_matchup", flaky_predict)

    log = io.StringIO()
    daily_update.run(log)  # must not raise despite one game failing

    assert len(calls) == 2  # both games were attempted
    assert "Failed to predict/log BBB @ AAA" in log.getvalue()
    assert "Logged 1/2 predictions" in log.getvalue()


def test_send_toast_invokes_pwsh_with_escaped_quotes(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append(args))

    daily_update.send_toast("Title with 'quote'", "Message with 'quote' too")

    assert len(calls) == 1
    args = calls[0]
    assert args[0] == daily_update.PWSH_EXE
    script = args[-1]
    assert "Title with ''quote''" in script
    assert "Message with ''quote'' too" in script


def test_load_and_save_notified_weeks_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_update, "NOTIFIED_WEEKS_PATH", tmp_path / "notified_weeks.json")
    assert daily_update._load_notified_weeks() == set()

    daily_update._save_notified_weeks({(2026, 1), (2026, 2)})
    assert daily_update._load_notified_weeks() == {(2026, 1), (2026, 2)}
