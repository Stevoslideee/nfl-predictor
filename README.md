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

When odds are available for a matchup, the Market comparison section also
shows a **Blended** number - a simple 50/50 average of the model's
probability and the market's. This is the one number in the whole app that
isn't backtested: The Odds API only exposes live/current odds, with no
historical archive to replay games against the way `backtest.py` does for
everything else, so there's no honest way to validate that 50/50 is the
right weight (versus, say, 70/30 toward the market, which is known to
out-predict any public model). It's shown as a clearly-labeled, directional
reference - not a calibrated probability like the model's own number.

Since it can't be backtested, it's validated the other way instead: every
real prediction with a market line attached is logged (`market_home_win_prob`
in `tracking.py`'s log), and once graded, the "Live tracking record" section
shows the model's, the market's, and the blend's actual accuracy and Brier
score side by side, over the same real games. That comparison starts out on
a small sample (only real, current-week games ever have odds attached) and
grows every week the daily automation runs - the honest way to find out
whether 50/50 was ever the right call, using real results instead of a
one-time guess.

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

**If a change to a file other than `app.py` doesn't seem to take effect:**
Streamlit's file-watcher reruns `app.py` on save, but doesn't reliably
re-import an already-imported module it doesn't own (`predict.py`,
`player_stats.py`, `live.py`, etc.) - edit `data.py` and the app might keep
using the old version until it's restarted. Stop the server (Ctrl+C) and
run it again rather than trusting a rerun for anything beyond `app.py`
itself. The deployed Community Cloud version can hit the same issue after
a quick succession of pushes - see "Deploy to Streamlit Community Cloud"
below for the fix there.

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
  Each team's top QB/RB/WR/TE also gets opponent-adjusted likelihoods for
  yardage (150+ passing, 40+ rushing/receiving), receptions (2-3+,
  position-dependent), and an anytime touchdown - see `props.py` below for
  how each is calculated.
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

## Deploy to Streamlit Community Cloud

Runs locally by default (above), but Streamlit's free Community Cloud
hosting will keep it always-on and reachable from your phone. This repo
is already set up for it - `.env` and `cache/` are gitignored (never
pushed), and `odds.py` reads the API key from Streamlit's own secrets
manager when a local `.env` isn't present, so no code changes are needed
either way.

1. Push this repo to GitHub (create a new repo at
   [github.com/new](https://github.com/new), public or private, then
   from this folder):
   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin master
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in
   with your GitHub account.
3. Click "New app", pick this repo/branch, and set the main file path to
   `app.py`.
4. If you use live odds, add your key under the app's **Settings → Secrets**
   (not `.env` - that file never leaves your machine) as:
   ```toml
   ODDS_API_KEY = "your_key_here"
   ```
5. Deploy. First load will be slow (it has to fetch and cache NFL data
   fresh, same as a local first run) - after that it's fast.

Community Cloud apps sleep after a period of inactivity and wake on the
next visit (a ~30-second cold start), which is normal for the free tier.

**If the deployed app throws an `AttributeError`/`ImportError` for
something that clearly exists in the code you just pushed:** Community
Cloud's auto-redeploy on push can hit the same stale-module-import issue
as the local dev server (see "Run the app" above) - it reruns `app.py`
but doesn't always freshly re-import every other module on a quick
succession of pushes. Fix: **⋮ menu → Reboot app** (in the app's
management panel) - a full process restart, not just a rerun, forces
every module to be freshly imported. Hit this once in practice after
several rapid commits; a reboot fixed it immediately.

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

## Live prediction tracking

`backtest.py` answers "how accurate is the model on history." `tracking.py`
answers "how is it actually doing, live, right now" - including a kind of
mistake pure win/loss accuracy can't see. A real week 2, 2026 game (LA vs.
NYG) showed the model call the winner correctly while assuming the wrong
starting QB (it expected J.Dart; J.Winston actually started, with no
injury designation ever flagging the change - checked three separate data
sources, including official depth charts, and none of them reflected the
real decision even the day after the game). No amount of "smarter" math
fixes that; it's a personnel problem, not a calibration problem. Tracking
makes it measurable instead of anecdotal.

Every real prediction made from the Weekly Report tab (or `weekly_report.py`)
is logged to `predictions/log.jsonl` (gitignored - it's your own running
history, not reproducible source, and grows continuously). Once a logged
game's real result comes in:

```bash
venv\Scripts\python tracking.py
```

grades it automatically: winner/margin accuracy (the live counterpart to
`backtest.py`'s historical numbers), and, per position, whether the
assumed starter/featured player actually was the real leader in that stat
that game - a prop is marked "personnel mismatch" rather than silently
graded wrong when the assumed player wasn't the one who actually played
that role. The same view is available in the app under the Weekly Report
tab's "Live tracking record" section.

**First real batch (2026 week 2, 16 games):** 62.5% winner accuracy (in
line with the ~64% backtested expectation for one week's worth of noise),
but only 55.5% personnel-assumption accuracy overall - and that number
hides a much more interesting split: the assumed **QB** was right in 14
of 16 games, but the assumed **WR** leader was right in only 2 of 16.
Real, quantified confirmation that who starts at QB is highly stable
week-to-week, while who leads a team in receiving yards genuinely isn't -
useful context for how much to trust a WR yardage prop versus a QB one.

### Fixing the WR/TE leader pick

That 2/16 WR result was surprising enough to check at scale rather than
trust from one week - and a home/away split that looked significant in
the same data (15/16 vs. 9/16, p=0.037) turned out to be pure small-sample
noise: replayed across ~2,400 real games (2016-2024), home vs. away
assumed-leader accuracy is statistically identical for every position
(p > 0.6 in all four cases). Good reminder that a pattern noticed *after*
seeing it needs a much bigger sample before it's trusted.

The underlying gap was real, though - and worse than one week suggested:

| Position | Assumed-leader accuracy (~4,860 real team-games) |
|---|---|
| QB | 79.5% |
| RB | 61.9% |
| TE | 60.0% |
| WR | 42.9% |

`player_stats.py` picked a team's featured RB/WR/TE by trailing
rushing+receiving *yards*. Tested the obvious alternative - trailing
*targets* - with the same fit(2016-2019)/holdout(2020-2024) discipline as
the Elo tuning: yards clearly wins for RB (a real rushing role is
yards-driven: 62% vs ~50% for targets), but targets meaningfully and
repeatably beats yards for WR (42.6% -> 45.6% on data never touched
during the comparison) and TE (60.6% -> 63.7%) - receiving yardage is
heavily skewed by big plays and game script, while targets reflect a more
stable "is the offense built around this player" signal. `player_stats.
_leader_for_position()` now ranks RB by yards and WR/TE by targets
(`_LEADER_RANK_STAT`); the combined "top skill players" display
(`_skill_leaders_from`) is unchanged, since it's informational only, not
used for prop targeting. WR is still the hardest position to call by a
wide margin - this is a real, validated improvement, not a fix.

### Running it automatically every day

`daily_update.py` logs the current week's predictions and re-grades
anything finished, meant to run unattended rather than depending on
someone remembering to open the app. Re-running daily (not just weekly)
is deliberate - each entry is timestamped and appended, never overwritten
(`tracking.log_prediction`), so it also captures how a prediction moved
as injury news firmed up over the week. Output goes to
`predictions/daily_run.log` (there's no console to print to when a
scheduled task runs unattended).

Set up as a Windows Scheduled Task (`schtasks`/Task Scheduler), once
daily:
```powershell
$action = New-ScheduledTaskAction -Execute "<path-to-venv>\Scripts\python.exe" -Argument "daily_update.py" -WorkingDirectory "<path-to-this-project>"
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "NFL Predictor Daily Update" -Action $action -Trigger $trigger -Settings $settings
```
`-StartWhenAvailable` means it catches up on the next login if the PC was
off at 8am, rather than silently skipping the day. This only runs
locally (a Streamlit Community Cloud deployment doesn't have a way to
run a scheduled background job) - if you're using the deployed version,
run `daily_update.py` locally to keep the tracking record current, or
just use the Weekly Report tab's button manually.

**Desktop notification when a week finishes grading:** rather than
having to check in, `daily_update.py` sends a Windows toast notification
(via the [BurntToast](https://github.com/Windos/BurntToast) PowerShell
module - `Install-Module -Name BurntToast -Scope CurrentUser`, a one-time
setup) the first time every game in a week has a real graded result -
not once per game, since games finish across different days and a ping
after just Thursday's game would be noise ahead of the real weekly
picture. Which weeks have already been notified about is tracked in
`predictions/notified_weeks.json` (gitignored, like the rest of
`predictions/`), so it fires exactly once per week even though the task
runs daily. No email/SMS account or credentials needed - fully local.
If your machine has both Windows PowerShell and PowerShell 7 installed,
make sure BurntToast is installed under the same one `daily_update.py`
invokes (`PWSH_EXE` at the top of the file) - they have separate module
paths, so installing into the wrong one means the notification call
fails every run (logged to `predictions/daily_run.log`, not silent, but
easy to miss if you're not checking that file).

## Run the tests

```bash
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m pytest tests/ -v
```

Unit tests for the model logic (Elo math, the QB-form tenure weighting,
prop-probability shrinkage, starter identification) and for
`daily_update.py`'s notification logic (fires once per fully-graded week,
never re-fires, retries on a failed send rather than marking it done) -
all on small, hand-built data or fully mocked dependencies rather than
real NFL history or a real PowerShell call, so the whole suite runs in
well under a second with no network, cache, or display dependency. This
catches regressions automatically instead of relying on a fresh manual
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
  changes. The current season's cache file refetches on its own once it's
  more than `CURRENT_SEASON_CACHE_MAX_AGE` (6 hours) old - found by hand
  more than once this session that a completed game's score or an updated
  injury designation was missing because the file cached hours or days
  earlier never refreshed; a fully completed past season still caches
  forever, since it genuinely can't change. Delete `cache/` to force a
  full fresh pull of everything regardless.
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
- **`props.py`** - opponent-adjusted probabilities for the Matchup
  Predictor's top QB/RB/WR/TE, covering yardage, receptions, and anytime
  touchdowns. Yardage and receptions (`prop_over_probability`) fit a normal
  distribution to the player's own trailing game log (real mean and
  variance, not assumed); touchdowns (`anytime_td_probability`) use a
  Poisson model instead, since TD counts are small, discrete, and
  right-skewed - a normal curve would put real probability mass on
  negative touchdowns, which a Poisson process doesn't. Both blend the
  player's own numbers toward the real league-wide value for that
  stat/position (`population_std()` / `population_td_rate()`) when a
  player has too little history of their own to trust alone - a rookie's
  first start or a new starter isn't hidden, but also isn't given a
  wildly overconfident number built on one data point. Both then shift
  by how much more or less than league-average the specific upcoming
  opponent has allowed in that stat recently (derived from
  `data.defense_allowed_view()` - nflverse has no direct "allowed" field,
  but a team's defense-allowed stats are just its opponents' own
  offensive output in those games). This is a standard technique (the
  same idea behind DFS/fantasy matchup ratings), not yet backtested for
  calibration the way the win-probability model is - treat it as
  directional context, not a precise forecast.
- **`backtest.py`** - replays history to measure real accuracy instead of
  assuming it, comparing plain Elo, Elo + QB form, and the full
  context-adjusted model side by side.
- **`tracking.py`** - logs every real prediction (Weekly Report tab/CLI) and
  grades it once the real game finishes: winner/margin accuracy, plus
  whether the assumed starter/featured player at each position actually
  was the real leader in that stat, plus - for the subset of games that had
  a real sportsbook line - the model's, market's, and 50/50 blend's
  accuracy side by side, so the blend (untested by design, since there's
  no historical odds archive) gets validated empirically over time instead
  of staying untested forever. See "Live prediction tracking" above.
- **`daily_update.py`** - unattended entry point for a Windows Scheduled
  Task: logs the current week's predictions and re-grades finished ones,
  once a day, without anyone opening the app.
- **`weekly_report.py`** - the model-vs-market comparison for a whole week's
  slate at once, shared by the Weekly Report tab and the standalone CLI.
- **`live.py`** - live/final scores and box scores from ESPN's public
  scoreboard feed (no API key needed), for the Live tab. Also exposes a live
  injury feed (`get_injuries`) that a real, current prediction (the
  Matchup Predictor tab, the Weekly Report tab, `daily_update.py`) can use
  to override the cached weekly injury designation with a fresher one -
  `predict_matchup`'s `live_injury_lookup` parameter, provided only for
  real predictions and never by `backtest.py`, so historical replays stay
  exactly reproducible.
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
- Real, current predictions now supplement the cached weekly injury report
  with ESPN's live feed (fresher, and not limited by `data.py`'s up-to-6-hour
  cache), but this only helps for a genuine injury-status change - it can't
  catch a healthy-scratch/depth-chart decision with no injury designation
  at all, which is exactly what happened in the week 2 2026 LA-vs-NYG game
  (see "Live prediction tracking" above): checked three separate data
  sources for that specific case, including official depth charts, and
  none of them ever reflected the real decision, even the day after the
  game. Some lineup surprises just aren't in any free structured data.
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
