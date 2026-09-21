import pandas as pd

from elo import BASE_RATING, SEASON_REGRESSION, expected_win_prob, mov_multiplier, run_elo


def test_expected_win_prob_equal_ratings_is_half():
    assert expected_win_prob(1500, 1500) == 0.5


def test_expected_win_prob_higher_rating_favored():
    assert expected_win_prob(1600, 1500) > 0.5
    assert expected_win_prob(1500, 1600) < 0.5


def test_expected_win_prob_symmetric():
    p = expected_win_prob(1550, 1450)
    q = expected_win_prob(1450, 1550)
    assert abs(p + q - 1.0) < 1e-9


def test_mov_multiplier_increases_with_margin():
    small = mov_multiplier(3, 0)
    big = mov_multiplier(35, 0)
    assert big > small


def test_mov_multiplier_positive():
    assert mov_multiplier(7, 100) > 0


def _schedule_row(game_id, season, week, home, away, home_score, away_score, gameday="2024-09-08"):
    return dict(
        game_id=game_id, season=season, week=week, home_team=home, away_team=away,
        home_score=home_score, away_score=away_score, gameday=gameday,
    )


def test_run_elo_winner_gains_rating_loser_loses():
    games = pd.DataFrame([_schedule_row("g1", 2024, 1, "BUF", "MIA", 30, 10)])
    state = run_elo(games)
    assert state.get("BUF") > BASE_RATING
    assert state.get("MIA") < BASE_RATING


def test_run_elo_narrow_win_moves_rating_less_than_a_blowout():
    narrow = pd.DataFrame([_schedule_row("g1", 2024, 1, "BUF", "MIA", 20, 17)])
    blowout = pd.DataFrame([_schedule_row("g1", 2024, 1, "BUF", "MIA", 45, 3)])
    narrow_shift = run_elo(narrow).get("BUF") - BASE_RATING
    blowout_shift = run_elo(blowout).get("BUF") - BASE_RATING
    assert 0 < narrow_shift < blowout_shift


def test_run_elo_tie_slightly_favors_the_underdog_side():
    # BUF is favored pre-game purely from home field, so a tie is a slight letdown for
    # BUF and a slight boost for MIA relative to what the pre-game odds implied
    games = pd.DataFrame([_schedule_row("g1", 2024, 1, "BUF", "MIA", 20, 20)])
    state = run_elo(games)
    assert state.get("BUF") < BASE_RATING
    assert state.get("MIA") > BASE_RATING


def test_run_elo_season_regression_pulls_ratings_toward_base():
    game1 = pd.DataFrame([_schedule_row("g1", 2024, 1, "BUF", "MIA", 40, 0, gameday="2024-09-08")])
    end_of_2024_rating = run_elo(game1).get("BUF")
    assert end_of_2024_rating > BASE_RATING  # sanity: the blowout win did move the rating

    both_games = pd.DataFrame([
        _schedule_row("g1", 2024, 1, "BUF", "MIA", 40, 0, gameday="2024-09-08"),
        _schedule_row("g2", 2025, 1, "BUF", "MIA", 0, 0, gameday="2025-09-08"),
    ])
    pre_g2_rating = run_elo(both_games).history[1]["pre_home_elo"]
    expected = BASE_RATING + SEASON_REGRESSION * (end_of_2024_rating - BASE_RATING)
    assert abs(pre_g2_rating - expected) < 1e-6


def test_run_elo_history_records_predicted_and_actual_winner():
    games = pd.DataFrame([_schedule_row("g1", 2024, 1, "BUF", "MIA", 30, 10)])
    state = run_elo(games)
    h = state.history[0]
    assert h["actual_winner"] == "BUF"
    assert h["predicted_winner"] in ("BUF", "MIA")


def test_get_returns_base_rating_for_unknown_team():
    state = run_elo(pd.DataFrame(columns=["game_id", "season", "week", "home_team", "away_team", "home_score", "away_score"]))
    assert state.get("XXX") == BASE_RATING
