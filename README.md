# NFL Matchup Predictor

A stats-driven NFL prediction tool: pick two teams and get a win probability
and projected margin, grounded in team Elo ratings built from every game
since 2010, each team's recent starting-QB performance, and four context
adjustments - QB injuries, rest days, divisional games, and weather (see
below). Also includes a live scores and player stats tab so you can watch
in-progress games with each player's current line shown next to their
recent-form average.

**Read this before you use it for anything:** this is an honest statistical
model, not an edge. Backtested against 2018-2024 (1,670 real games):

| Model | Straight-up accuracy | Brier score (lower = better calibrated) |
|---|---|---|
| Plain Elo | 64.4% | 0.2222 |
| + QB form | 64.1% | 0.2226 |
| + full context (injury/rest/division/weather) | 65.0% | 0.2215 |

The full-context version picks meaningfully more winners than plain Elo (65.0%
vs. 64.4%) while also producing the best-calibrated probabilities of the
three - most of that gap comes from the QB-injury swap, the one situation
Elo genuinely can't already know about (see "Fixing the QB-form adjustment"
below). Sportsbook closing lines - the actual market, after all information
is priced in - hit roughly 65-67% straight-up. No public model beats the
closing line consistently, so 65.0% puts this right at the edge of what's
realistic without insider information. Use this as one input to your own
judgment, never as a guarantee, and never bet more than you can afford to lose.

## The four context adjustments

Each of these is small, backtested (not guessed), and documented here so
none of it is a black box:

- **QB injuries** - if the usual starter is listed Out/Doubtful, the model
  finds whoever's next in line at QB (by recent snap volume) and uses *their*
  trailing stats instead of pretending the starter is playing. If no backup
  has any recent snaps to go on (e.g. a brand-new signing), it falls back to
  a neutral league-average QB rather than guessing.
- **Rest days** - a modest Elo adjustment favoring the more-rested team
  (`home_rest`/`away_rest` from the schedule data), capped small since the
  research on rest advantage is itself modest.
- **Divisional games** - historically closer/more upset-prone, so the
  model's confidence is pulled toward a coin flip for these games rather
  than the pick being flipped outright.
- **Weather** - high wind (20+ mph) or extreme cold (25°F or below)
  suppresses passing offense and adds variance, which is modeled the same
  way as divisional games: it closes the gap between favorite and underdog,
  it doesn't say who benefits. For games already played, this uses the
  actual recorded conditions; for upcoming outdoor games, it fetches a live
  forecast from [open-meteo.com](https://open-meteo.com/) (free, no API key).

All four show up as plain-English notes under the prediction (e.g. "S.Darnold
is out - using D.Lock's recent form instead", "Divisional game - historically
closer than the raw numbers suggest") rather than silently changing a number.

### Fixing the QB-form adjustment

The standalone "+QB form" step used to make accuracy slightly *worse* than
plain Elo, every time it was measured. The original formula compared a
QB's trailing 5-game passer rating against a flat league average and added
that straight onto Elo, for every game, established starter or not.

Tested that against a held-out stretch of seasons the tuning never saw
(same fit-2010-2019/test-2020-2024 discipline as the Elo constants above),
along with an alternative - comparing a QB to their *own* longer-run
baseline instead of the league average, to catch hot/cold streaks. Every
parameterization of both approaches won on the fit seasons and lost to
plain Elo on the untouched holdout, consistently, across dozens of
combinations - a textbook overfitting signature, not real signal. The
likely reason: Elo is fit game-by-game on real outcomes, so an established
starter's level is already priced in; a noisy 5-game rating layered on top
just adds noise, not information.

The one case Elo genuinely can't have absorbed yet is a *new* starter - a
rookie's first start, a just-inserted injury replacement - who hasn't
played enough games for the team's rating to reflect them. The fix weights
the adjustment by how little of the team's last 15 QB-games this player
accounts for (`player_stats.QB_TENURE_WINDOW`): near-full strength for a
brand-new starter, fading to near zero for an established one, where Elo
is already the better signal. That change alone doesn't manufacture new
accuracy in the no-injury case - it now ties plain Elo instead of losing to
it - but it materially sharpens the exact scenario it's meant for: the
full-context backtest (which includes the injury swap) went from 64.3% to
65.0% accuracy after this change, since a freshly-inserted backup's low
tenure now gets the full-strength adjustment instead of a diluted one.

## Optional: live sportsbook odds

The predictor tab can show a real sportsbook line next to the model's own
probability, so you can see where they agree or disagree. This needs a free
API key (500 requests/month) from [the-odds-api.com](https://the-odds-api.com/):

1. Sign up yourself at the-odds-api.com and copy your API key.
2. Create a file named `.env` in this project folder (same folder as
   `app.py`) containing one line: `ODDS_API_KEY=your_key_here`
3. Restart the app. The Market comparison section in the predictor tab will
   pick it up automatically.

Without a key, everything else still works - that section just shows a
reminder instead of odds. The key is only ever sent to The Odds API itself.

## Setup

Already done once, but if you need to redo it:

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

## Run the app

```bash
venv\Scripts\streamlit run app.py
```

Opens at http://localhost:8501. First run downloads NFL data (schedules and
weekly player stats since 2010) and caches it locally in `cache/` as parquet
files, so later runs are fast. Delete `cache/` to force a fresh pull.

The app has three tabs:

- **Matchup Predictor** - pick a real game from the "Quick-pick" dropdown
  (auto-fills the teams and runs the prediction) or choose any two teams
  manually. Shows the win-probability model described above, a live
  sportsbook line comparison (if configured), and projected QB/RB/WR/TE
  stat lines - with team ratings, the injury report, and head-to-head
  history tucked into expanders so the page stays scannable. If either
  starting QB is Out/Doubtful, the prediction automatically swaps in their
  backup's recent form and says so; Questionable gets an info note without
  a swap. Rest, divisional, and weather notes show up here too when they apply.
  Each team's top QB/RB/WR/TE also gets an opponent-adjusted likelihood of
  clearing a yardage threshold (150+ passing, 40+ rushing/receiving) - see
  `props.py` below for how that's calculated.
- **Live & Recent Player Stats** - current or past-week scores (auto-refreshes
  every 30s while a game is live), with a full box score per team, each
  team's injury report, and each player's trailing 5-game average shown
  alongside their current-game line.
- **Weekly Report** - a plain-English verdict for every game on one week's
  slate at once: predicted winner and margin, a qualitative confidence label
  (Toss-up/Lean/Solid/Strong pick, no percentages to parse), whether the
  sportsbook market agrees, and an "attack note" naming each team's leading
  passer and skill player from their own recent form. Below that, **Season
  so far** replays every game from week 1 through the selected week and
  shows what the model called against what actually happened, scored fairly
  using only the data available before each week's kickoff.

## Run the backtest

```bash
venv\Scripts\python backtest.py --start 2018 --end 2024
```

Replays real historical games chronologically, scoring the model's
predictions against actual outcomes. This is how the numbers in the table
above were generated - re-run it any time to sanity-check accuracy after
changing the model. Pass `--skip-context` to compare only plain Elo vs.
Elo + QB form (faster - skips loading injury data and computing the
injury/rest/division/weather variant).

## Run the tests

```bash
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m pytest tests/ -v
```

Unit tests for the model logic (Elo math, the QB-form tenure weighting,
prop-probability shrinkage, starter identification) - all on small,
hand-built data rather than real NFL history, so the whole suite runs in
well under a second with no network or cache dependency. This catches
regressions automatically instead of relying on a fresh manual
verification script for every change, which is how every fix in this
project was checked before the suite existed. It's a unit suite, not a
substitute for `backtest.py` - accuracy claims are still validated there,
against real games.

## Run the weekly report from the terminal

```bash
venv\Scripts\python weekly_report.py --season 2026 --week 3
```

Same model-vs-market comparison as the Weekly Report tab, printed as a plain
table - useful for scripting or a quick terminal check without opening the app.

## How it works

- **`data.py`** - pulls schedules from `nfl_data_py` and weekly player stats
  directly from nflverse's actively maintained release (the package's own
  `import_weekly_data` points at a legacy release that stopped updating after
  the 2024 season). The season range always runs from 2010 through the
  current year, so it automatically picks up new seasons without code
  changes - just delete `cache/` (or wait for the season number to roll
  over) to pull fresh data.
- **`elo.py`** - a FiveThirtyEight-style Elo rating: home-field bonus, a
  margin-of-victory multiplier so blowouts move ratings more, and
  between-season regression toward the mean since rosters change. The
  K-factor, home-field bonus, and regression amount were tuned by grid
  search on 2010-2019 and validated on a held-out 2020-2024 stretch the
  search never saw, rather than assumed from 538's own published values -
  the fitted constants generalized to real held-out games (+0.9-1.3pts
  accuracy, better Brier, across every near-tied candidate from the
  search), which is the honest way to know a tuning change is signal and
  not overfitting to one decade's quirks (e.g. home-field advantage
  dropping league-wide after 2020).
- **`player_stats.py`** - trailing-5-game form for each team's current
  starting QB (passer rating, yards/game) and top skill-position players,
  used both to nudge the prediction and to explain it. `backup_qb_form()`
  finds whoever's next in line at QB when the starter is hurt. Also tracks
  each QB's tenure (`_qb_tenure`, `QB_TENURE_WINDOW`) - how many of the
  team's last 15 QB-games they've actually started - so `predict.py` can
  tell a newly-installed starter from an established one.
  `team_form_snapshot()` computes all of this from one team-filtered slice
  of the data; a caller scoring many games for the same week (Weekly
  Report, season recap) filters the full history once via
  `weekly_hist_as_of()` and reuses it across every game, instead of each
  prediction rescanning the whole dataset on its own.
- **`predict.py`** - combines Elo, the QB-form adjustment, and the four
  context adjustments (injury/rest/division/weather) into a final win
  probability and projected point margin. `qb_elo_adjustment` weights its
  passer-rating comparison by tenure - see "Fixing the QB-form adjustment"
  above. Each adjustment is its own small, pure function
  (`qb_elo_adjustment`, `rest_elo_adjustment`, `divisional_dampening_factor`,
  `weather_dampening_factor`) so `backtest.py` can call the exact same logic
  used live, instead of a separately-maintained copy that could drift out
  of sync.
- **`weather.py`** - live forecasts for outdoor stadiums via open-meteo.com
  (free, no API key), with a hardcoded coordinate table for all 32 teams.
  Only called for upcoming games at outdoor stadiums; past games use the
  actual recorded temp/wind already in the schedule data.
- **`props.py`** - "will this player clear N yards" probabilities for the
  Matchup Predictor's top QB/RB/WR/TE. Fits a normal distribution to the
  player's own trailing game log (real mean and variance, not assumed),
  blending in the real league-wide variance for that stat/position
  (`population_std()`) when a player has too little history of their own
  to trust their own sample variance - a rookie's first start or a new
  starter isn't hidden, but also isn't given a wildly overconfident number
  built on one data point. Then shifts that mean by how much more or less
  than league-average the specific upcoming opponent has allowed in that
  stat recently (derived
  from `data.defense_allowed_view()` - nflverse has no direct "yards
  allowed" field, but a team's defense-allowed stats are just its
  opponents' own offensive output in those games). This is a standard
  technique (the same idea behind DFS/fantasy matchup ratings), not yet
  backtested for calibration the way the win-probability model is - treat
  it as directional context, not a precise forecast.
- **`backtest.py`** - replays history to measure real accuracy instead of
  assuming it, comparing plain Elo, Elo + QB form, and the full
  context-adjusted model side by side.
- **`weekly_report.py`** - the model-vs-market comparison for a whole week's
  slate at once, shared by the Weekly Report tab and the standalone CLI.
- **`live.py`** - live/final scores and box scores from ESPN's public
  scoreboard feed (no API key needed), for the Live tab.
- **`injuries.py`** - official weekly injury report lookups (no API key
  needed) - the QB's status drives the backup-swap in `predict.py`; every
  other injury is still shown as plain context rather than folded into the
  math, since impact varies too much by player and scheme to guess at
  honestly for non-QB positions.
- **`odds.py`** - optional live sportsbook odds from The Odds API, devigged
  to a fair win probability and compared against the model's own number.
- **`app.py`** - the Streamlit UI (dark theme configured in
  `.streamlit/config.toml`).

## Known limitations

- The backup-QB swap only knows about players who've already taken recent
  snaps for that team - a brand-new signing with zero recent attempts won't
  be found, and the model falls back to a neutral league-average QB instead.
- Weather adjustments only trigger past a threshold (20+ mph wind, 25°F or
  colder) - mild weather is correctly ignored, but this means the model
  can't distinguish "totally calm" from "breezy but not disruptive."
- No last-minute lineup news beyond the official injury report (a
  surprise inactive announced an hour before kickoff won't be reflected).
- Player prop probabilities are a normal-distribution approximation, not yet
  backtested for calibration - useful as directional context, not a precise
  forecast. With fewer than a few games of their own history (a rookie's
  first start, a new starter), a player's variance is blended toward the
  real league-wide variance for that stat/position (see `props.py`) so the
  estimate doesn't rely on an unreliable small sample alone - it still
  fades to almost pure self-history once a player has a full trailing
  window of games.
- The full-context model (65.0% backtested accuracy) is close to but still
  short of sportsbook closing lines (65-67%) - expected, since the market
  prices in information (beat writers, practice reports, weather calls
  made minutes before kickoff) this model has no access to. NFL games are
  also genuinely hard to predict beyond a point; no public model has ever
  consistently beaten the closing line.
