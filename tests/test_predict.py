import pandas as pd

import player_stats
from conftest import qb_row, weekly_df
from elo import EloState
from predict import (
    MAX_QB_ELO_ADJUSTMENT,
    MAX_REST_ADJUSTMENT,
    divisional_dampening_factor,
    predict_matchup,
    qb_elo_adjustment,
    rest_elo_adjustment,
    weather_dampening_factor,
)

EMPTY_SCHEDULE_COLUMNS = [
    "game_id", "season", "week", "home_team", "away_team", "home_score", "away_score",
    "gameday", "div_game", "home_rest", "away_rest", "roof", "temp", "wind",
]


def _qb_form(rating, tenure):
    return {"player_name": "X", "passer_rating": rating, "tenure": tenure}


def test_qb_elo_adjustment_zero_when_ratings_equal():
    assert qb_elo_adjustment(_qb_form(95, 0), _qb_form(95, 0)) == 0.0


def test_qb_elo_adjustment_full_strength_for_brand_new_starter():
    # tenure=0 (just took over) gets the adjustment at exactly full strength - no shrinkage
    home = _qb_form(100, 0)  # 10 points above league average, brand new
    away = _qb_form(90, 0)   # exactly average, tenure irrelevant here
    from predict import ELO_PER_PASSER_RATING_POINT
    adj = qb_elo_adjustment(home, away)
    assert adj == (100 - 90) * ELO_PER_PASSER_RATING_POINT


def test_qb_elo_adjustment_near_zero_for_established_starter_mismatch():
    # both fully established (tenure == window) - the whole point of the tenure fix is
    # that this case gets a much smaller adjustment than the raw rating gap would imply
    home = _qb_form(120, player_stats.QB_TENURE_WINDOW)
    away = _qb_form(60, player_stats.QB_TENURE_WINDOW)
    adj = qb_elo_adjustment(home, away)
    assert adj == 0.0  # weight collapses to exactly 0 at tenure == window


def test_qb_elo_adjustment_respects_cap_both_directions():
    home = _qb_form(158, 0)
    away = _qb_form(0, 0)
    assert qb_elo_adjustment(home, away) == MAX_QB_ELO_ADJUSTMENT
    assert qb_elo_adjustment(away, home) == -MAX_QB_ELO_ADJUSTMENT


def test_qb_elo_adjustment_missing_rating_defaults_to_league_average():
    unknown = {"player_name": None, "passer_rating": None, "tenure": 0}
    strong_new_starter = _qb_form(120, 0)  # 30 above average, full weight
    # unknown defaults to exactly 90 (league average), so this is equivalent to a
    # 90-vs-120 comparison, fully weighted, then capped
    assert qb_elo_adjustment(unknown, strong_new_starter) == -MAX_QB_ELO_ADJUSTMENT


def test_rest_elo_adjustment_none_when_data_missing():
    assert rest_elo_adjustment(None, 3) == 0.0
    assert rest_elo_adjustment(7, None) == 0.0


def test_rest_elo_adjustment_favors_more_rested_team():
    assert rest_elo_adjustment(10, 6) > 0
    assert rest_elo_adjustment(6, 10) < 0


def test_rest_elo_adjustment_capped():
    assert rest_elo_adjustment(20, 0) == MAX_REST_ADJUSTMENT
    assert rest_elo_adjustment(0, 20) == -MAX_REST_ADJUSTMENT


def test_divisional_dampening_factor():
    assert divisional_dampening_factor(False) == 1.0
    assert 0 < divisional_dampening_factor(True) < 1.0


def test_weather_dampening_factor_no_effect_below_thresholds():
    assert weather_dampening_factor(temp_f=60, wind_mph=5) == 1.0


def test_weather_dampening_factor_wind_only():
    factor = weather_dampening_factor(temp_f=60, wind_mph=25)
    assert factor < 1.0


def test_weather_dampening_factor_cold_only():
    factor = weather_dampening_factor(temp_f=10, wind_mph=5)
    assert factor < 1.0


def test_weather_dampening_factor_combines_both():
    wind_only = weather_dampening_factor(temp_f=60, wind_mph=25)
    both = weather_dampening_factor(temp_f=10, wind_mph=25)
    assert both < wind_only  # combining both effects should dampen more than either alone


def test_weather_dampening_factor_none_values_ignored():
    assert weather_dampening_factor(None, None) == 1.0


def _established_qb_weekly(name, team, n_games=5):
    return [
        qb_row(name, team, 2024, w, completions=20, attempts=30, passing_yards=250, passing_tds=2, interceptions=1)
        for w in range(1, n_games + 1)
    ]


def test_predict_matchup_without_live_lookup_uses_cached_injuries_only():
    weekly = weekly_df(_established_qb_weekly("A.QB", "AAA") + _established_qb_weekly("B.QB", "BBB"))
    schedules = pd.DataFrame(columns=EMPTY_SCHEDULE_COLUMNS)
    pred = predict_matchup(schedules, weekly, "AAA", "BBB", 2024, 6, elo_state=EloState())
    assert pred.home_qb_status is None  # no injuries DataFrame, no live lookup - nothing to report
    assert pred.home_qb["player_name"] == "A.QB"


def test_predict_matchup_live_lookup_overrides_status_and_triggers_backup_swap():
    weekly = weekly_df(_established_qb_weekly("A.QB", "AAA") + _established_qb_weekly("B.QB", "BBB"))
    schedules = pd.DataFrame(columns=EMPTY_SCHEDULE_COLUMNS)

    def lookup(team, qb_name):
        return "Out" if team == "AAA" else None

    pred = predict_matchup(schedules, weekly, "AAA", "BBB", 2024, 6, elo_state=EloState(), live_injury_lookup=lookup)
    assert pred.home_qb_status == "Out"
    # no backup logged for AAA in this fixture, so it should fall back to a neutral QB
    # and say so - the important thing is the live status was actually used at all
    assert pred.home_qb["player_name"] is None
    assert "A.QB is out" in pred.home_qb_note


def test_predict_matchup_live_lookup_returning_none_keeps_cached_status():
    weekly = weekly_df(_established_qb_weekly("A.QB", "AAA") + _established_qb_weekly("B.QB", "BBB"))
    schedules = pd.DataFrame(columns=EMPTY_SCHEDULE_COLUMNS)

    calls = []

    def lookup(team, qb_name):
        calls.append((team, qb_name))
        return None  # "no fresher info" - must not overwrite anything

    pred = predict_matchup(schedules, weekly, "AAA", "BBB", 2024, 6, elo_state=EloState(), live_injury_lookup=lookup)
    assert pred.home_qb_status is None
    assert pred.away_qb_status is None
    assert ("AAA", "A.QB") in calls
    assert ("BBB", "B.QB") in calls
