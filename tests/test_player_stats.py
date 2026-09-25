import player_stats
from player_stats import (
    QB_TENURE_WINDOW,
    _leader_for_position,
    _qb_tenure,
    _starting_qb_from,
    before_cutoff,
    passer_rating,
    qb_trailing_form,
    team_form_snapshot,
)
from conftest import qb_row, skill_row, weekly_df


def test_passer_rating_zero_attempts():
    assert passer_rating({"attempts": 0}) == 0.0


def test_passer_rating_perfect_game_caps_at_158_3():
    # a mathematically "perfect" passer rating game: 77.5%+ comp, 12.5+ yds/att,
    # 11.875%+ TD rate, 0 INT - each component caps at 2.375, giving exactly 158.3
    stats = {"completions": 20, "attempts": 20, "passing_yards": 300, "passing_tds": 5, "interceptions": 0}
    assert abs(passer_rating(stats) - 158.3) < 0.1


def test_before_cutoff_excludes_current_and_future_weeks():
    df = weekly_df([qb_row("Q", "BUF", 2024, w) for w in range(1, 5)])
    result = before_cutoff(df, 2024, 3)
    assert set(result["week"]) == {1, 2}


def test_before_cutoff_excludes_future_seasons():
    df = weekly_df([qb_row("Q", "BUF", 2023, 17), qb_row("Q", "BUF", 2024, 1)])
    result = before_cutoff(df, 2024, 1)
    assert list(result["season"]) == [2023]


def test_starting_qb_from_picks_highest_volume():
    df = weekly_df([
        qb_row("Backup", "BUF", 2024, 1, attempts=5),
        qb_row("Starter", "BUF", 2024, 1, attempts=35),
    ])
    assert _starting_qb_from(df) == "Starter"


def test_starting_qb_from_ties_go_to_more_recent():
    df = weekly_df([
        qb_row("OldGuy", "BUF", 2024, 1, attempts=30),
        qb_row("NewGuy", "BUF", 2024, 2, attempts=30),
    ])
    assert _starting_qb_from(df) == "NewGuy"


def test_starting_qb_from_empty_returns_none():
    df = weekly_df([skill_row("R.Back", "RB", "BUF", 2024, 1, carries=10)])
    assert _starting_qb_from(df) is None


def test_qb_tenure_full_window_for_long_starter(established_qb_history):
    tenure = _qb_tenure(established_qb_history, "J.Established")
    assert tenure == QB_TENURE_WINDOW  # started every one of the last window games


def test_qb_tenure_low_for_recent_starter(new_starter_history):
    tenure = _qb_tenure(new_starter_history, "J.New")
    assert tenure == 4  # started the last 4 of the team's games, out of a 15-game window
    assert tenure < QB_TENURE_WINDOW


def test_qb_trailing_form_reflects_tenure(new_starter_history):
    form = qb_trailing_form(new_starter_history, "BUF", 2024, 17)
    assert form["player_name"] == "J.New"  # out-volumes the predecessor within the trailing window
    assert form["tenure"] == 4


def test_qb_trailing_form_no_qb_history_returns_neutral():
    df = weekly_df([skill_row("R.Back", "RB", "BUF", 2024, 1, carries=10)])
    form = qb_trailing_form(df, "BUF", 2024, 2)
    assert form["player_name"] is None
    assert form["passer_rating"] is None


def test_team_form_snapshot_shape():
    rows = [qb_row("Q", "BUF", 2024, w) for w in range(1, 6)]
    rows += [skill_row("R.Back", "RB", "BUF", 2024, w, carries=15, rushing_yards=60) for w in range(1, 6)]
    hist = before_cutoff(weekly_df(rows), 2024, 6)
    snap = team_form_snapshot(hist, "BUF")
    assert snap["qb"]["player_name"] == "Q"
    assert snap["rb"]["player_name"] == "R.Back"
    assert snap["wr"] is None
    assert snap["te"] is None
    assert isinstance(snap["skill"], list)


def test_leader_for_position_rb_ranks_by_yards():
    # high-yardage back should win even with fewer targets - validated: yards is the
    # right signal for RB (a real rushing role is yards-driven)
    rows = [skill_row("Workhorse", "RB", "BUF", 2024, w, carries=20, rushing_yards=100, targets=1) for w in range(1, 6)]
    rows += [skill_row("PassCatcher", "RB", "BUF", 2024, w, carries=2, rushing_yards=10, targets=8) for w in range(1, 6)]
    hist = before_cutoff(weekly_df(rows), 2024, 6)
    leader = _leader_for_position(hist[hist["recent_team"] == "BUF"], "RB")
    assert leader["player_name"] == "Workhorse"


def test_leader_for_position_wr_ranks_by_targets_not_yards():
    # WR is ranked by trailing TARGETS, not yards - validated against real historical
    # games (see README): a low-target big-play WR should lose to a high-target,
    # lower-yardage possession WR, the opposite of what a yards-based ranking would pick
    rows = [skill_row("BigPlay", "WR", "BUF", 2024, w, receiving_yards=90, targets=3, receptions=2) for w in range(1, 6)]
    rows += [skill_row("Possession", "WR", "BUF", 2024, w, receiving_yards=50, targets=10, receptions=8) for w in range(1, 6)]
    hist = before_cutoff(weekly_df(rows), 2024, 6)
    leader = _leader_for_position(hist[hist["recent_team"] == "BUF"], "WR")
    assert leader["player_name"] == "Possession"


def test_leader_for_position_te_ranks_by_targets_not_yards():
    rows = [skill_row("BigPlay", "TE", "BUF", 2024, w, receiving_yards=80, targets=2, receptions=1) for w in range(1, 6)]
    rows += [skill_row("Possession", "TE", "BUF", 2024, w, receiving_yards=40, targets=9, receptions=7) for w in range(1, 6)]
    hist = before_cutoff(weekly_df(rows), 2024, 6)
    leader = _leader_for_position(hist[hist["recent_team"] == "BUF"], "TE")
    assert leader["player_name"] == "Possession"


def test_leader_for_position_none_when_no_candidates():
    hist = before_cutoff(weekly_df([qb_row("Q", "BUF", 2024, 1)]), 2024, 2)
    assert _leader_for_position(hist[hist["recent_team"] == "BUF"], "WR") is None


def test_espn_name_to_nflverse_basic():
    assert player_stats.espn_name_to_nflverse("Josh Allen") == "J.Allen"


def test_espn_name_to_nflverse_drops_suffix():
    assert player_stats.espn_name_to_nflverse("Michael Pittman Jr.") == "M.Pittman"


def _box_row(player, category, labels, stats):
    return {"category": category, "player": player, "labels": labels, "stats": stats}


_PASS_LABELS = ["C/ATT", "YDS", "AVG", "TD", "INT", "SACKS", "QBR", "RTG"]
_RUSH_LABELS = ["CAR", "YDS", "AVG", "TD", "LONG"]
_REC_LABELS = ["REC", "YDS", "AVG", "TD", "LONG", "TGTS"]


def test_live_top_performers_picks_the_real_starter_by_yards():
    # the real case this feature exists for: whoever actually threw the passes, not
    # whoever the model assumed pre-game
    box = {
        "ATL": [
            _box_row("Michael Penix Jr.", "passing", _PASS_LABELS, ["18/25", "256", "10.2", "1", "1", "0-0", "84.5", "101.4"]),
        ]
    }
    result = player_stats.live_top_performers(box)
    assert result["ATL"]["passing"]["player"] == "Michael Penix Jr."
    assert result["ATL"]["passing"]["yards"] == 256.0
    assert result["ATL"]["passing"]["line"] == "18/25, 256 yds, 1 TD, 1 INT"


def test_live_top_performers_ranks_multiple_players_by_yards():
    box = {
        "ATL": [
            _box_row("Bijan Robinson", "rushing", _RUSH_LABELS, ["29", "194", "6.7", "2", "55"]),
            _box_row("Brian Robinson Jr.", "rushing", _RUSH_LABELS, ["10", "50", "5.0", "1", "16"]),
        ]
    }
    result = player_stats.live_top_performers(box)
    assert result["ATL"]["rushing"]["player"] == "Bijan Robinson"
    assert result["ATL"]["rushing"]["line"] == "29 car, 194 yds, 2 TD"


def test_live_top_performers_receiving_line():
    box = {"GB": [_box_row("Matthew Golden", "receiving", _REC_LABELS, ["5", "100", "20.0", "1", "45", "12"])]}
    result = player_stats.live_top_performers(box)
    assert result["GB"]["receiving"]["line"] == "5 rec, 100 yds, 1 TD"


def test_live_top_performers_ignores_non_offensive_categories():
    box = {"ATL": [_box_row("Some Kicker", "kicking", ["FG"], ["1/1"])]}
    assert player_stats.live_top_performers(box) == {"ATL": {}}


def test_live_top_performers_empty_box_score():
    assert player_stats.live_top_performers({}) == {}


def test_live_top_performers_handles_missing_yards_gracefully():
    box = {"ATL": [_box_row("Nobody", "passing", ["C/ATT"], ["0/0"])]}  # no YDS column at all
    assert player_stats.live_top_performers(box) == {"ATL": {}}
