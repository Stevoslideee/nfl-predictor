"""Shared test fixtures. All tests use small, hand-built DataFrames rather than real
network data, so the suite runs instantly and deterministically - no cache, no internet,
no dependency on which NFL season happens to be "current" when the tests run.
"""
import pandas as pd
import pytest

WEEKLY_COLUMNS = [
    "player_name", "position", "recent_team", "season", "week",
    "completions", "attempts", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
]


def qb_row(player_name, team, season, week, completions=20, attempts=30, passing_yards=250,
           passing_tds=2, interceptions=1):
    return dict(
        player_name=player_name, position="QB", recent_team=team, season=season, week=week,
        completions=completions, attempts=attempts, passing_yards=passing_yards,
        passing_tds=passing_tds, interceptions=interceptions,
        carries=0, rushing_yards=0, rushing_tds=0, receptions=0, targets=0,
        receiving_yards=0, receiving_tds=0,
    )


def skill_row(player_name, position, team, season, week, carries=0, rushing_yards=0,
              rushing_tds=0, receptions=0, targets=0, receiving_yards=0, receiving_tds=0):
    return dict(
        player_name=player_name, position=position, recent_team=team, season=season, week=week,
        completions=0, attempts=0, passing_yards=0, passing_tds=0, interceptions=0,
        carries=carries, rushing_yards=rushing_yards, rushing_tds=rushing_tds,
        receptions=receptions, targets=targets, receiving_yards=receiving_yards,
        receiving_tds=receiving_tds,
    )


def weekly_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=WEEKLY_COLUMNS)


@pytest.fixture
def make_weekly():
    """Returns the weekly_df builder so tests can do make_weekly([qb_row(...), ...])."""
    return weekly_df


@pytest.fixture
def established_qb_history():
    """One team, one QB, 20 consecutive starts - a clearly "established" starter for
    tenure-based tests (QB_TENURE_WINDOW is 15)."""
    return weekly_df([qb_row("J.Established", "BUF", 2024, w, passing_yards=250 + w) for w in range(1, 21)])


@pytest.fixture
def new_starter_history():
    """One team where a new QB has started the last 4 of the team's games, after a
    long-tenured predecessor. _starting_qb_from identifies the current starter by
    trailing attempt VOLUME, so a genuinely new starter needs enough recent games of
    their own to outweigh the predecessor's remaining games within that same window -
    a single start wouldn't yet out-volume 4 of a predecessor's games, which is itself
    a real (pre-existing) property of volume-based starter identification, not
    something to paper over here."""
    rows = [qb_row("J.Old", "BUF", 2024, w) for w in range(1, 13)]
    rows += [qb_row("J.New", "BUF", 2024, w, passing_yards=300) for w in range(13, 17)]
    return weekly_df(rows)
