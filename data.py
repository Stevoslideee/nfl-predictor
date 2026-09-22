"""Data loading and local caching for NFL schedules, team results, and player weekly stats."""

import datetime as dt
import io
from pathlib import Path

import nfl_data_py as nfl
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# How stale the CURRENT season's cached file is allowed to get before refetching. Found
# by hand more than once this session (a cached schedule missing a game's just-final
# score, a stale weekly-stats file) - a season still in progress keeps gaining new games
# and updated statuses, unlike a completed one, which never changes again once cached.
CURRENT_SEASON_CACHE_MAX_AGE = dt.timedelta(hours=6)


def _cached_per_season(prefix: str, seasons: list[int], loader) -> pd.DataFrame:
    """Cache one file per season, not per requested range - so a range like 2024-2026
    reuses whatever 2010-2026 (or any other overlapping range) already fetched, instead
    of re-downloading seasons we already have every time the requested range changes.

    A season still in progress (this calendar year or later) is refetched once its cache
    file is older than CURRENT_SEASON_CACHE_MAX_AGE, since it keeps gaining new games and
    updated statuses; a season that's clearly over is cached forever, since it can't
    change - this is the common case and stays exactly as cheap as before.
    """
    current_year = dt.date.today().year
    frames = []
    for season in seasons:
        path = CACHE_DIR / f"{prefix}_{season}.parquet"
        is_current = season >= current_year
        stale = (
            is_current and path.exists()
            and dt.datetime.now() - dt.datetime.fromtimestamp(path.stat().st_mtime) > CURRENT_SEASON_CACHE_MAX_AGE
        )
        if path.exists() and not stale:
            frames.append(pd.read_parquet(path))
        else:
            df = loader(season)
            df.to_parquet(path)
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_schedules(seasons: list[int]) -> pd.DataFrame:
    """Game-level schedule and final scores for each season."""
    return _cached_per_season("schedules", seasons, lambda s: nfl.import_schedules([s]))


WEEKLY_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{0}.parquet"

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=6, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])))


WEEKLY_STATS_COLUMNS = [
    "player_name", "position", "recent_team", "season", "week",
    "completions", "attempts", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
]


def _fetch_one_season_weekly(season: int) -> pd.DataFrame:
    """Per-player, per-week box score stats for one season, straight from nflverse's
    actively maintained release (nfl_data_py's own import_weekly_data still points at a
    legacy release that stopped being updated after the 2024 season, so it 404s for 2025+).

    The source file has 150+ columns (EPA, air yards, defensive/kicking stats, etc.) we
    never use - trimming to what we need keeps every filter operation on this data cheap,
    since pandas has to reindex every column on each boolean-mask selection.
    """
    resp = _session.get(WEEKLY_STATS_URL.format(season), timeout=30)
    resp.raise_for_status()
    df = pd.read_parquet(io.BytesIO(resp.content))
    df = df.rename(columns={"team": "recent_team", "passing_interceptions": "interceptions"})
    return df[WEEKLY_STATS_COLUMNS]


def load_weekly_player_stats(seasons: list[int]) -> pd.DataFrame:
    """Per-player, per-week box score stats."""
    return _cached_per_season("weekly", seasons, _fetch_one_season_weekly)


TEAM_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{0}.parquet"

TEAM_STATS_COLUMNS = [
    "team", "opponent_team", "season", "week",
    "rushing_yards", "receiving_yards", "passing_yards",
    "rushing_tds", "receiving_tds", "receptions",
]


def _fetch_one_season_team_stats(season: int) -> pd.DataFrame:
    """Team-level weekly offensive output, one row per (team, week). There's no direct
    'yards allowed' field in nflverse's data, but since each row already names the
    opponent, a team's defense-allowed stats are just its opponents' own offensive rows
    for those same games - see `defense_allowed_view()`.
    """
    resp = _session.get(TEAM_STATS_URL.format(season), timeout=30)
    resp.raise_for_status()
    df = pd.read_parquet(io.BytesIO(resp.content))
    return df[TEAM_STATS_COLUMNS]


def load_team_weekly_stats(seasons: list[int]) -> pd.DataFrame:
    """Team-level weekly offensive stats (rushing/receiving/passing yards and TDs,
    receptions), keyed by (team, opponent_team, season, week).

    Cached under a "v2" prefix - the plain "team_stats" prefix was used before TD/
    reception columns were added, so pre-existing "team_stats_{season}.parquet" files
    lack them. Reusing that prefix would silently read stale, narrower cached files
    instead of re-fetching, causing a KeyError the first time a TD/reception column
    is used.
    """
    return _cached_per_season("team_stats_v2", seasons, _fetch_one_season_team_stats)


def defense_allowed_view(team_stats: pd.DataFrame) -> pd.DataFrame:
    """Reframe team-level offensive output as what the OPPONENT's defense allowed that
    week - team A's own rushing/receiving/passing yards (and TDs, receptions) in a given
    game are exactly what team B's defense gave up, so this is a rename, not a new fetch."""
    return team_stats.rename(
        columns={
            "team": "offense_team",
            "opponent_team": "team",
            "rushing_yards": "rushing_yards_allowed",
            "receiving_yards": "receiving_yards_allowed",
            "passing_yards": "passing_yards_allowed",
            "rushing_tds": "rushing_tds_allowed",
            "receiving_tds": "receiving_tds_allowed",
            "receptions": "receptions_allowed",
        }
    )


def load_injuries(seasons: list[int]) -> pd.DataFrame:
    """Official weekly NFL injury reports (practice status, game designation)."""
    return _cached_per_season("injuries", seasons, lambda s: nfl.import_injuries([s]))


def load_team_desc() -> pd.DataFrame:
    """Team metadata (names, abbreviations, colors)."""
    path = CACHE_DIR / "team_desc.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = nfl.import_team_desc()
    df.to_parquet(path)
    return df


def completed_games(schedules: pd.DataFrame) -> pd.DataFrame:
    """Only games that have final scores, sorted chronologically."""
    df = schedules.dropna(subset=["home_score", "away_score"]).copy()
    df["gameday"] = pd.to_datetime(df["gameday"])
    return df.sort_values(["gameday", "game_id"]).reset_index(drop=True)
