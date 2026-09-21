"""Live sportsbook odds from The Odds API (https://the-odds-api.com), compared against
the model's own win probability so you can see where they agree or disagree.

Requires a free API key (500 requests/month on the free tier) - sign up yourself at
https://the-odds-api.com/, then either:
  - set the ODDS_API_KEY environment variable, or
  - create a file named `.env` in this project folder containing: ODDS_API_KEY=your_key_here

This module never sends your key anywhere except The Odds API itself.
"""

import os
from pathlib import Path

import requests

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"

# The Odds API uses full franchise names; map them to nflverse's team abbreviations.
TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Los Angeles Rams": "LA",
    "Los Angeles Chargers": "LAC",
    "Las Vegas Raiders": "LV",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


class OddsApiError(Exception):
    pass


def _load_env_file() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_api_key() -> str | None:
    _load_env_file()
    key = os.environ.get("ODDS_API_KEY")
    if key:
        return key
    # Streamlit Community Cloud has no .env file - secrets are set through its own
    # dashboard and read via st.secrets, not always mirrored into os.environ. Falling
    # back to it here means the same code works unmodified locally and once deployed.
    try:
        import streamlit as st

        return st.secrets.get("ODDS_API_KEY")
    except Exception:
        return None


def american_to_prob(price: int) -> float:
    if price > 0:
        return 100 / (price + 100)
    return -price / (-price + 100)


def fetch_odds(regions: str = "us", markets: str = "h2h,spreads") -> list[dict]:
    """Current NFL odds across bookmakers, devigged to a fair win probability per team."""
    api_key = get_api_key()
    if not api_key:
        raise OddsApiError(
            "No Odds API key configured. Sign up for a free key at https://the-odds-api.com/ "
            "and save it in a .env file in this project as ODDS_API_KEY=your_key_here."
        )

    try:
        resp = requests.get(
            ODDS_API_BASE,
            params={"apiKey": api_key, "regions": regions, "markets": markets, "oddsFormat": "american"},
            timeout=15,
        )
    except requests.RequestException as e:
        raise OddsApiError(f"Couldn't reach The Odds API ({e.__class__.__name__}) - try again shortly.") from e

    if resp.status_code == 401:
        raise OddsApiError("The Odds API rejected the key (401) - double check it's correct in .env.")
    if resp.status_code == 429:
        raise OddsApiError("The Odds API's free tier (500 requests/month) looks exhausted - odds will return once it resets.")
    try:
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise OddsApiError(f"The Odds API returned something unexpected ({e.__class__.__name__}).") from e

    games = []
    for event in payload:
        try:
            home_name, away_name = event["home_team"], event["away_team"]
            home_abbr = TEAM_NAME_TO_ABBR.get(home_name)
            away_abbr = TEAM_NAME_TO_ABBR.get(away_name)

            home_probs, away_probs, home_spreads = [], [], []
            for book in event.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market["key"] == "h2h":
                        outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
                        if home_name in outcomes and away_name in outcomes:
                            h_raw = american_to_prob(outcomes[home_name])
                            a_raw = american_to_prob(outcomes[away_name])
                            total = h_raw + a_raw  # remove the bookmaker's vig by normalizing to 1.0
                            home_probs.append(h_raw / total)
                            away_probs.append(a_raw / total)
                    elif market["key"] == "spreads":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == home_name:
                                home_spreads.append(outcome["point"])
        except (KeyError, TypeError, ZeroDivisionError):
            # one malformed event (an unexpected field, a book with a weird payload)
            # shouldn't take down odds for the rest of the week's games
            continue

        if not home_probs:
            continue

        games.append(
            {
                "commence_time": event["commence_time"],
                "home_team": home_abbr or home_name,
                "away_team": away_abbr or away_name,
                "home_win_prob": sum(home_probs) / len(home_probs),
                "away_win_prob": sum(away_probs) / len(away_probs),
                "home_spread": sum(home_spreads) / len(home_spreads) if home_spreads else None,
                "num_books": len(home_probs),
            }
        )
    return games


def find_matchup(games: list[dict], home_team: str, away_team: str) -> dict | None:
    wanted = {home_team, away_team}
    for g in games:
        if {g["home_team"], g["away_team"]} == wanted:
            return g
    return None


def blended_probability(model_prob: float, market_prob: float) -> float:
    """A simple, even average of the model's own win probability and the market's
    devigged implied probability - shown as an additional, clearly-labeled number, not
    a replacement for either.

    Unlike every other adjustment in this project, this weight (50/50) is NOT backtested
    against real history: The Odds API only exposes live/current odds, with no historical
    archive to replay games against the way backtest.py does for everything else. A
    market-weighted blend is well-motivated in principle (markets aggregate information -
    beat writers, injury news, sharp money - a public model has no access to), but the
    specific 50/50 split here is a reasonable default, not a validated one. Treat it as
    directional, same as the prop probabilities.
    """
    return (model_prob + market_prob) / 2
