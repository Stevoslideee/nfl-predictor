"""Live weather forecasts for outdoor NFL stadiums, via open-meteo.com (free, no API
key). Used as a small dampening factor on the model's confidence - bad weather (high
wind, extreme cold) suppresses passing offense and adds variance to a game, which tends
to close the gap between favorite and underdog rather than say who specifically benefits.

For past/completed games, use the actual temp/wind columns already in nflverse's
schedule data instead of this module - a forecast API has nothing useful to say about
last season. This is only for games that haven't been played yet.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# A shared Session avoids re-building a connection pool (and re-parsing the OS
# certificate trust store) on every call - a real cost (~0.4-1.4s) that otherwise gets
# paid independently by every thread in prefetch_forecasts' concurrent fetches.
_session = requests.Session()

# Approximate stadium coordinates for all 32 teams. Good enough for a regional weather
# read - we don't need rooftop precision, just "is it windy/cold in this city today."
STADIUM_COORDS = {
    "ARI": (33.5276, -112.2626),
    "ATL": (33.7554, -84.4008),
    "BAL": (39.2780, -76.6227),
    "BUF": (42.7738, -78.7870),
    "CAR": (35.2258, -80.8528),
    "CHI": (41.8623, -87.6167),
    "CIN": (39.0954, -84.5160),
    "CLE": (41.5061, -81.6995),
    "DAL": (32.7473, -97.0945),
    "DEN": (39.7439, -105.0201),
    "DET": (42.3400, -83.0456),
    "GB": (44.5013, -88.0622),
    "HOU": (29.6847, -95.4107),
    "IND": (39.7601, -86.1639),
    "JAX": (30.3239, -81.6373),
    "KC": (39.0489, -94.4839),
    "LA": (33.9535, -118.3392),
    "LAC": (33.9535, -118.3392),
    "LV": (36.0909, -115.1833),
    "MIA": (25.9580, -80.2389),
    "MIN": (44.9738, -93.2575),
    "NE": (42.0909, -71.2643),
    "NO": (29.9511, -90.0812),
    "NYG": (40.8135, -74.0745),
    "NYJ": (40.8135, -74.0745),
    "PHI": (39.9008, -75.1675),
    "PIT": (40.4468, -80.0158),
    "SEA": (47.5952, -122.3316),
    "SF": (37.4030, -121.9700),
    "TB": (27.9759, -82.5033),
    "TEN": (36.1665, -86.7713),
    "WAS": (38.9078, -76.8645),
}

# Domes and fixed/typically-closed roofs never need a weather adjustment. Retractable
# roofs (ARI, ATL, DAL, HOU, IND, LV... ) are usually closed in bad weather anyway, so
# nflverse's own `roof` value for that game (open vs. closed on the day) is what decides
# it - this set is just "never even worth checking."
ALWAYS_INDOOR = {"DET", "MIN", "NO", "LV"}


def is_outdoor(roof: str | None, team: str) -> bool:
    """Whether weather could plausibly matter for this game."""
    if team in ALWAYS_INDOOR:
        return False
    if roof is None:
        return True  # unknown - safer to check than to silently skip
    return roof not in ("dome", "closed")


@lru_cache(maxsize=256)
def get_forecast(team: str, game_date: str) -> dict | None:
    """Midday forecast (temp F, wind mph) for this team's home city on this date.

    `game_date` is 'YYYY-MM-DD'. Returns None on any failure (missing coordinates, no
    forecast that far out, network issue) - callers should treat that as "no weather
    adjustment," not an error.

    Cached per (team, date) for the life of the process - a whole week's slate only has
    a handful of distinct dates, and this avoids re-fetching the same forecast on every
    Streamlit rerun or every game in a batch report.
    """
    coords = STADIUM_COORDS.get(team)
    if not coords:
        return None
    lat, lon = coords

    try:
        resp = _session.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "start_date": game_date,
                "end_date": game_date,
            },
            timeout=10,
        )
        resp.raise_for_status()
        hourly = resp.json().get("hourly", {})
        temps = hourly.get("temperature_2m") or []
        winds = hourly.get("wind_speed_10m") or []
        if not temps or not winds:
            return None
        # Most NFL kickoffs are afternoon/early evening local time; hour 15 (3pm) is a
        # reasonable single-value stand-in without needing the exact kickoff time.
        idx = min(15, len(temps) - 1, len(winds) - 1)
        return {"temp_f": round(temps[idx], 1), "wind_mph": round(winds[idx], 1)}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def prefetch_forecasts(team_dates: list[tuple[str, str]]) -> None:
    """Warm the forecast cache for several (team, date) pairs concurrently.

    A whole week's slate can have a dozen-plus outdoor games needing a live forecast;
    fetching them one at a time inside the per-game prediction loop turns a ~2s report
    into an ~7s one on a cold cache. Call this once up front with every (team, date) the
    upcoming batch will need, and the per-game loop then hits a warm cache instead of
    the network. Safe to call with duplicates or with pairs already cached.
    """
    unique = {(team, date) for team, date in team_dates if team and date}
    if not unique:
        return
    with ThreadPoolExecutor(max_workers=min(16, len(unique))) as pool:
        list(pool.map(lambda td: get_forecast(*td), unique))
