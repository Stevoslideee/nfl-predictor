"""_cached_per_season is the foundation every loader (schedules, weekly stats, team
stats, injuries) shares. Found by hand more than once this session that a cached file
for the CURRENT season goes stale (a just-finished game's score missing, a QB swap not
reflected) since the old version cached forever regardless of age - these tests lock in
the fix so it can't quietly regress."""
import datetime as dt
import os

import pandas as pd
import pytest

import data


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)


def _write_cache_file(prefix: str, season: int, age: dt.timedelta | None = None) -> None:
    path = data.CACHE_DIR / f"{prefix}_{season}.parquet"
    pd.DataFrame({"season": [season]}).to_parquet(path)
    if age is not None:
        old_time = (dt.datetime.now() - age).timestamp()
        os.utime(path, (old_time, old_time))


def test_past_season_never_refetched_regardless_of_age():
    past_season = dt.date.today().year - 5
    _write_cache_file("schedules", past_season, age=dt.timedelta(days=3000))

    calls = []
    loader = lambda s: calls.append(s) or pd.DataFrame({"season": [s], "fresh": [True]})
    result = data._cached_per_season("schedules", [past_season], loader)

    assert calls == []  # loader never called - a completed season can't change
    assert "fresh" not in result.columns  # confirms the cached (not freshly-loaded) file was used


def test_current_season_fresh_cache_not_refetched():
    current_season = dt.date.today().year
    _write_cache_file("schedules", current_season, age=dt.timedelta(minutes=5))

    calls = []
    loader = lambda s: calls.append(s) or pd.DataFrame({"season": [s], "fresh": [True]})
    data._cached_per_season("schedules", [current_season], loader)

    assert calls == []  # well within CURRENT_SEASON_CACHE_MAX_AGE - no refetch needed


def test_current_season_stale_cache_is_refetched():
    current_season = dt.date.today().year
    _write_cache_file("schedules", current_season, age=dt.timedelta(hours=7))

    calls = []
    loader = lambda s: calls.append(s) or pd.DataFrame({"season": [s], "fresh": [True]})
    result = data._cached_per_season("schedules", [current_season], loader)

    assert calls == [current_season]  # older than CURRENT_SEASON_CACHE_MAX_AGE (6h) - refetched
    assert result["fresh"].iloc[0] == True


def test_future_season_treated_as_current_for_staleness():
    # a season that hasn't started yet (or a rolled-over year) is still "in progress"
    # from a caching standpoint, not "complete" - so it must follow the same staleness
    # rule as the current season, not be cached forever like a past one
    future_season = dt.date.today().year + 1
    _write_cache_file("schedules", future_season, age=dt.timedelta(hours=7))

    calls = []
    loader = lambda s: calls.append(s) or pd.DataFrame({"season": [s], "fresh": [True]})
    data._cached_per_season("schedules", [future_season], loader)

    assert calls == [future_season]


def test_missing_file_always_fetched():
    season = dt.date.today().year - 3
    calls = []
    loader = lambda s: calls.append(s) or pd.DataFrame({"season": [s]})
    data._cached_per_season("schedules", [season], loader)

    assert calls == [season]
    assert (data.CACHE_DIR / f"schedules_{season}.parquet").exists()  # written for next time
