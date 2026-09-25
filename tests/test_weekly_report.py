import weekly_report


def test_live_qb_summary_shows_both_teams_real_qb():
    top_performers = {
        "GB": {"passing": {"player": "Jordan Love", "yards": 312.0, "line": "28/53, 312 yds, 2 TD, 1 INT"}},
        "ATL": {"passing": {"player": "Michael Penix Jr.", "yards": 256.0, "line": "18/25, 256 yds, 1 TD, 1 INT"}},
    }
    assert weekly_report.live_qb_summary("GB", "ATL", top_performers) == "GB: Jordan Love · ATL: Michael Penix Jr."


def test_live_qb_summary_handles_a_team_with_no_passing_stats_yet():
    top_performers = {"GB": {"passing": {"player": "Jordan Love", "yards": 10.0, "line": "1/2, 10 yds, 0 TD, 0 INT"}}}
    assert weekly_report.live_qb_summary("GB", "ATL", top_performers) == "GB: Jordan Love"


def test_live_qb_summary_returns_dash_when_nobody_has_played_yet():
    assert weekly_report.live_qb_summary("GB", "ATL", {}) == "-"
