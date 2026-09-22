"""Streamlit UI: an NFL matchup predictor plus a live/recent game stats viewer."""

import datetime as dt

import pandas as pd
import streamlit as st

import injuries as injuries_mod
import live
import odds as odds_mod
import player_stats
import tracking
from data import load_injuries, load_schedules, load_team_weekly_stats, load_weekly_player_stats
from predict import (
    RB_REC_THRESHOLD,
    TE_REC_THRESHOLD,
    WR_REC_THRESHOLD,
    defense_hist_as_of,
    elo_state_as_of,
    predict_matchup,
    prefetch_weather_for_matchups,
    weekly_hist_as_of,
)
from weekly_report import build_recap_row, build_report_row, favorite

SEASONS = list(range(2010, dt.date.today().year + 1))
INJURY_SEASONS = list(range(dt.date.today().year - 2, dt.date.today().year + 1))

st.set_page_config(page_title="NFL Matchup Predictor", page_icon="🏈", layout="centered")
st.title("🏈 NFL Matchup Predictor")


@st.cache_data(show_spinner="Loading NFL history (first run downloads and caches it locally)...")
def get_history():
    schedules = load_schedules(SEASONS)
    weekly = load_weekly_player_stats(SEASONS)
    teams = sorted(schedules["home_team"].dropna().unique().tolist())
    return schedules, weekly, teams


@st.cache_data(ttl=3600, show_spinner="Loading injury reports...")
def get_injuries():
    return load_injuries(INJURY_SEASONS)


@st.cache_data(ttl=30, show_spinner="Checking live scores...")
def get_scoreboard_cached(week, season):
    return live.get_scoreboard(week=week, season=season)


@st.cache_data(ttl=30, show_spinner="Loading box score...")
def get_boxscore_cached(game_id):
    return live.get_boxscore(game_id)


@st.cache_data(ttl=1800, show_spinner="Checking sportsbook odds...")
def get_odds_cached():
    return odds_mod.fetch_odds(), dt.datetime.now()


@st.cache_data(show_spinner="Building team ratings...")
def get_elo_state_cached(season, week):
    return elo_state_as_of(schedules, season, week)


@st.cache_data(show_spinner=False)
def get_weekly_hist_cached(season, week):
    return weekly_hist_as_of(weekly, season, week)


@st.cache_data(show_spinner=False)
def get_team_stats_cached():
    return load_team_weekly_stats(SEASONS)


@st.cache_data(show_spinner=False)
def get_defense_hist_cached(season, week):
    return defense_hist_as_of(team_stats, season, week)


try:
    schedules, weekly, teams = get_history()
    injuries_df = get_injuries()
    team_stats = get_team_stats_cached()
except Exception as e:
    st.error(f"Couldn't load NFL data ({e.__class__.__name__}). Check your connection and reload.")
    st.stop()

predict_tab, live_tab, week_tab = st.tabs(["Matchup Predictor", "Live & Recent Player Stats", "Weekly Report"])

with predict_tab:
    st.caption("Elo ratings + recent QB form. An informed opinion, not a guarantee — see the README for backtested accuracy.")

    current_year = dt.date.today().year
    if "season_input" not in st.session_state or "week_input" not in st.session_state:
        default_board = get_scoreboard_cached(None, None)
        st.session_state.setdefault("season_input", default_board["season"] or current_year)
        st.session_state.setdefault("week_input", default_board["week"] or 1)

    sc1, sc2 = st.columns(2)
    with sc1:
        season = st.number_input("Season", min_value=SEASONS[0], max_value=current_year + 1, key="season_input")
    with sc2:
        week = st.number_input("Week (predict as of before this week)", min_value=1, max_value=22, key="week_input")

    def _apply_quick_pick():
        picked = st.session_state.get("quick_pick")
        if picked and picked != NO_QUICK_PICK:
            g = st.session_state["quick_pick_games"][picked]
            st.session_state["home_team_select"] = g["home_team"]
            st.session_state["away_team_select"] = g["away_team"]
            st.session_state.show_prediction = True

    NO_QUICK_PICK = "-- pick a game for this week --"
    week_board = get_scoreboard_cached(int(week), int(season))
    if week_board["games"]:
        game_labels = {}
        for g in week_board["games"]:
            score = f" ({g['away_score']}-{g['home_score']})" if g["status"] != "Scheduled" else ""
            game_labels[f"{g['away_team']} @ {g['home_team']} — {g['status']}{score}"] = g
        st.session_state["quick_pick_games"] = game_labels
        qp_week_key = (int(season), int(week))
        if st.session_state.get("_quick_pick_week_key") != qp_week_key:
            st.session_state["quick_pick"] = NO_QUICK_PICK
            st.session_state["_quick_pick_week_key"] = qp_week_key
        st.selectbox(
            "Quick-pick a game this week",
            [NO_QUICK_PICK] + list(game_labels.keys()),
            key="quick_pick",
            on_change=_apply_quick_pick,
        )
    else:
        st.caption("No games found for that season/week to quick-pick from.")

    st.session_state.setdefault("home_team_select", "KC" if "KC" in teams else teams[0])

    col1, col2 = st.columns(2)
    with col1:
        home_team = st.selectbox("Home team", teams, key="home_team_select")
    with col2:
        away_options = [t for t in teams if t != home_team]
        if st.session_state.get("away_team_select") not in away_options:
            st.session_state["away_team_select"] = away_options[0]
        away_team = st.selectbox("Away team", away_options, key="away_team_select")

    if st.button("Predict", type="primary"):
        st.session_state.show_prediction = True

    if st.session_state.get("show_prediction"):
        elo_state = get_elo_state_cached(int(season), int(week))
        weekly_hist = get_weekly_hist_cached(int(season), int(week))
        defense_hist = get_defense_hist_cached(int(season), int(week))
        pred = predict_matchup(
            schedules, weekly, home_team, away_team, int(season), int(week),
            injuries=injuries_df, elo_state=elo_state, weekly_hist=weekly_hist, defense_hist=defense_hist,
        )

        st.subheader(f"{away_team} @ {home_team}")
        prob_pct = pred.home_win_prob * 100
        winner = home_team if pred.home_win_prob >= 0.5 else away_team
        confidence = max(prob_pct, 100 - prob_pct)

        st.metric(
            f"Projected winner: {winner}",
            f"{confidence:.0f}% confidence",
            f"{home_team} {pred.projected_margin:+.1f} pts"
            if pred.projected_margin >= 0
            else f"{away_team} {-pred.projected_margin:+.1f} pts",
        )
        st.progress(pred.home_win_prob, text=f"{home_team} win probability: {prob_pct:.0f}%")

        for team, status, note in [
            (home_team, pred.home_qb_status, pred.home_qb_note),
            (away_team, pred.away_qb_status, pred.away_qb_note),
        ]:
            if note:
                st.warning(f"⚠️ {team}: {note}")
            elif status == "Questionable":
                st.info(f"ℹ️ {team}'s starting QB is listed **Questionable** (still using their own stats).")

        for note in pred.context_notes:
            st.caption(f"↳ {note}")

        mc_header, mc_refresh = st.columns([4, 1])
        mc_header.markdown("**Market comparison**")
        if mc_refresh.button("🔄 Refresh", key="refresh_odds_predict"):
            get_odds_cached.clear()

        if not odds_mod.get_api_key():
            st.info(
                "No sportsbook odds connected yet. Sign up for a free key at "
                "[the-odds-api.com](https://the-odds-api.com/) (500 requests/month free), then "
                "create a file named `.env` in the project folder containing:\n\n"
                "`ODDS_API_KEY=your_key_here`"
            )
        else:
            try:
                market_games, fetched_at = get_odds_cached()
                st.caption(f"Odds as of {fetched_at.strftime('%I:%M:%S %p')} (cached up to 30 min - hit Refresh for the latest)")
                match = odds_mod.find_matchup(market_games, home_team, away_team)
                if match is None:
                    st.caption(
                        "No current market odds found for this matchup (only upcoming/current-week "
                        "games have odds posted)."
                    )
                else:
                    market_pct = match["home_win_prob"] * 100
                    edge = prob_pct - market_pct
                    k_team, k_pct, k_margin = favorite(home_team, away_team, match["home_win_prob"], match["home_spread"])
                    market_line = f"**Market favors {k_team}** to win, {k_pct:.0f}%" + (
                        f", by {k_margin:.1f} points" if k_margin is not None else ""
                    )
                    st.markdown(f"{market_line} (from {match['num_books']} sportsbooks).")

                    blended_pct = odds_mod.blended_probability(pred.home_win_prob, match["home_win_prob"]) * 100

                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric(f"Model: {home_team} win%", f"{prob_pct:.0f}%")
                    mc2.metric(f"Market: {home_team} win%", f"{market_pct:.0f}%", f"{match['num_books']} books")
                    mc3.metric("Model vs. market", f"{edge:+.0f} pts")
                    mc4.metric(f"Blended (untested): {home_team} win%", f"{blended_pct:.0f}%")
                    st.caption(
                        "Blended is a simple 50/50 average of model and market, shown for "
                        "reference - unlike everything else here, this weighting isn't "
                        "backtested (The Odds API has no historical archive to validate "
                        "against). Treat it as directional, not a calibrated number."
                    )
                    if winner != k_team:
                        st.caption(f"⚠️ Model and market disagree on the winner ({winner} vs. {k_team}) — check the injury report.")
                    elif abs(edge) >= 8:
                        st.caption("⚠️ Wide gap between model and market — likely missing context (injury, weather, motivation).")
            except odds_mod.OddsApiError as e:
                st.warning(str(e))

        def player_line(label: str, data: dict | None) -> str:
            if not data:
                return f"{label}: no recent data"
            name = data["player_name"]
            if label == "QB":
                return (
                    f"**{label} {name}** — {data['pass_yards_per_game']} pass yds, "
                    f"{data['pass_tds_per_game']} TD, {data['interceptions_per_game']} INT "
                    f"(avg, last {data['games']} gm)"
                )
            return (
                f"**{label} {name}** — {data['receptions_per_game']} rec, {data['receiving_yards_per_game']} rec yds "
                f"({data['targets_per_game']} tgts); {data['carries_per_game']} car, {data['rushing_yards_per_game']} rush yds; "
                f"{data['tds_per_game']} TD (avg, last {data['games']} gm)"
            )

        def show_prop(threshold: int, prop: dict | None) -> None:
            if not prop:
                return
            pct = prop["probability"] * 100
            st.markdown(
                f"&nbsp;&nbsp;↳ {pct:.0f}% chance of {threshold}+ yds "
                f"(own avg {prop['own_avg']}, matchup-adjusted {prop['matchup_adjusted_avg']})",
                unsafe_allow_html=True,
            )

        def show_rec_prop(threshold: float, prop: dict | None) -> None:
            if not prop:
                return
            pct = prop["probability"] * 100
            st.markdown(
                f"&nbsp;&nbsp;↳ {pct:.0f}% chance of {threshold:g}+ receptions "
                f"(own avg {prop['own_avg']}, matchup-adjusted {prop['matchup_adjusted_avg']})",
                unsafe_allow_html=True,
            )

        def show_td_prop(prop: dict | None) -> None:
            if not prop:
                return
            pct = prop["probability"] * 100
            st.markdown(
                f"&nbsp;&nbsp;↳ {pct:.0f}% chance of a TD "
                f"(own rate {prop['own_avg']}/gm, matchup-adjusted {prop['matchup_adjusted_avg']}/gm)",
                unsafe_allow_html=True,
            )

        with st.expander("📊 Projected key players (QB / RB / WR / TE)"):
            st.caption(
                "Each player's own trailing 5-game average, plus opponent-adjusted "
                "likelihoods for yardage, receptions, and touchdowns. Yardage/receptions "
                "use a normal-distribution estimate; touchdowns use a Poisson model "
                "(more appropriate for a small, discrete count) - neither is a guarantee, "
                "and neither is yet backtested for calibration the way the win-probability "
                "model is."
            )
            pc1, pc2 = st.columns(2)
            with pc1:
                st.caption(home_team)
                st.markdown(player_line("QB", pred.home_qb))
                show_prop(150, pred.home_qb_prop)
                st.markdown(player_line("RB", pred.home_rb))
                show_prop(40, pred.home_rb_prop)
                show_rec_prop(RB_REC_THRESHOLD, pred.home_rb_rec_prop)
                show_td_prop(pred.home_rb_td_prop)
                st.markdown(player_line("WR", pred.home_wr))
                show_prop(40, pred.home_wr_prop)
                show_rec_prop(WR_REC_THRESHOLD, pred.home_wr_rec_prop)
                show_td_prop(pred.home_wr_td_prop)
                st.markdown(player_line("TE", pred.home_te))
                show_prop(40, pred.home_te_prop)
                show_rec_prop(TE_REC_THRESHOLD, pred.home_te_rec_prop)
                show_td_prop(pred.home_te_td_prop)
            with pc2:
                st.caption(away_team)
                st.markdown(player_line("QB", pred.away_qb))
                show_prop(150, pred.away_qb_prop)
                st.markdown(player_line("RB", pred.away_rb))
                show_prop(40, pred.away_rb_prop)
                show_rec_prop(RB_REC_THRESHOLD, pred.away_rb_rec_prop)
                show_td_prop(pred.away_rb_td_prop)
                st.markdown(player_line("WR", pred.away_wr))
                show_prop(40, pred.away_wr_prop)
                show_rec_prop(WR_REC_THRESHOLD, pred.away_wr_rec_prop)
                show_td_prop(pred.away_wr_td_prop)
                st.markdown(player_line("TE", pred.away_te))
                show_prop(40, pred.away_te_prop)
                show_rec_prop(TE_REC_THRESHOLD, pred.away_te_rec_prop)
                show_td_prop(pred.away_te_td_prop)

        with st.expander("🏈 Team ratings & top skill players"):
            ec1, ec2 = st.columns(2)
            with ec1:
                st.markdown(f"**{home_team} Elo rating:** {pred.home_elo}")
                qb = pred.home_qb
                if qb["player_name"]:
                    st.markdown(
                        f"**Starting QB:** {qb['player_name']}  \n"
                        f"Last {qb['games']} games: {qb['passer_rating']} passer rating, "
                        f"{qb['pass_yards_per_game']} yds/gm"
                    )
                for p in pred.home_skill:
                    st.markdown(
                        f"- {p['player_name']}: {p['receptions_per_game']} rec, {p['receiving_yards_per_game']} rec yds, "
                        f"{p['rushing_yards_per_game']} rush yds (last {p['games']})"
                    )
            with ec2:
                st.markdown(f"**{away_team} Elo rating:** {pred.away_elo}")
                qb = pred.away_qb
                if qb["player_name"]:
                    st.markdown(
                        f"**Starting QB:** {qb['player_name']}  \n"
                        f"Last {qb['games']} games: {qb['passer_rating']} passer rating, "
                        f"{qb['pass_yards_per_game']} yds/gm"
                    )
                for p in pred.away_skill:
                    st.markdown(
                        f"- {p['player_name']}: {p['receptions_per_game']} rec, {p['receiving_yards_per_game']} rec yds, "
                        f"{p['rushing_yards_per_game']} rush yds (last {p['games']})"
                    )

        if not pred.home_injuries.empty or not pred.away_injuries.empty:
            with st.expander("🩹 Injury report"):
                ic1, ic2 = st.columns(2)
                with ic1:
                    st.caption(home_team)
                    if pred.home_injuries.empty:
                        st.caption("No notable injuries listed.")
                    else:
                        st.dataframe(pred.home_injuries, hide_index=True, width='stretch')
                with ic2:
                    st.caption(away_team)
                    if pred.away_injuries.empty:
                        st.caption("No notable injuries listed.")
                    else:
                        st.dataframe(pred.away_injuries, hide_index=True, width='stretch')

        if not pred.head_to_head.empty:
            with st.expander("🔁 Recent head-to-head"):
                st.dataframe(pred.head_to_head, hide_index=True, width='stretch')

        st.caption(
            "Statistical estimate from public play-by-play data, not betting advice. "
            "Never wager more than you can afford to lose."
        )

with live_tab:
    st.caption("Live scores + box scores (auto-refresh 30s), each player's line next to their recent-form average.")

    browse_past = st.checkbox("Browse a past week instead of the current one")
    sb_week = sb_season = None
    if browse_past:
        bc1, bc2 = st.columns(2)
        with bc1:
            sb_season = st.number_input(
                "Season", min_value=2010, max_value=dt.date.today().year, value=dt.date.today().year, key="live_season"
            )
        with bc2:
            sb_week = st.number_input("Week", min_value=1, max_value=22, value=1, key="live_week")

    if st.button("Refresh scores"):
        get_scoreboard_cached.clear()
        get_boxscore_cached.clear()

    scoreboard = get_scoreboard_cached(sb_week, sb_season)
    games = scoreboard["games"]

    if not games:
        st.info("No games found for that week.")
    else:
        def label(g):
            flag = "🔴 LIVE" if g["is_live"] else g["status"]
            score = f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            extra = f" (Q{g['period']} {g['clock']})" if g["is_live"] else ""
            return f"{flag} — {score}{extra}"

        choice = st.selectbox("Game", games, format_func=label)

        if choice:
            box = get_boxscore_cached(choice["game_id"])
            game_season = scoreboard["season"] or dt.date.today().year
            game_week = scoreboard["week"] or 1

            for team_abbr in [choice["away_team"], choice["home_team"]]:
                st.subheader(team_abbr)

                team_injuries = injuries_mod.team_injury_report(injuries_df, team_abbr, game_season, game_week)
                if not team_injuries.empty:
                    with st.expander(f"{team_abbr} injury report"):
                        st.dataframe(team_injuries, hide_index=True, width='stretch')

                rows = box.get(team_abbr, [])
                shown_categories = [c for c in ("passing", "rushing", "receiving") if any(r["category"] == c for r in rows)]

                if not shown_categories:
                    st.caption("No box score available yet for this game.")
                    continue

                for cat in shown_categories:
                    cat_rows = [r for r in rows if r["category"] == cat]
                    if not cat_rows:
                        continue
                    labels = cat_rows[0]["labels"]
                    table = pd.DataFrame([[r["player"], *r["stats"]] for r in cat_rows], columns=["Player", *labels])
                    st.markdown(f"**{cat.title()}**")
                    st.dataframe(table, hide_index=True, width='stretch')

                    for r in cat_rows:
                        nflverse_name = player_stats.espn_name_to_nflverse(r["player"])
                        recent = player_stats.recent_form_for_player(
                            weekly, nflverse_name, team_abbr, game_season, game_week
                        )
                        if recent:
                            position = recent["position"]
                            key_stats = ", ".join(
                                f"{k.replace('_', ' ')}: {v}"
                                for k, v in recent.items()
                                if k not in ("games", "position") and v not in (0, 0.0)
                            )
                            st.caption(f"↳ {position} {r['player']} — last {recent['games']} games average: {key_stats}")
                        else:
                            st.caption(f"↳ {r['player']} — no recent history on file")

    st.caption("ESPN live data + official NFL history. Name-matching is best-effort — a line may occasionally be missing.")

with week_tab:
    st.caption("Model vs. market favorite for every game this week — flags a big gap or a different pick entirely.")

    wc1, wc2, wc3 = st.columns([2, 2, 1])
    with wc1:
        wk_season = st.number_input(
            "Season", min_value=2010, max_value=dt.date.today().year + 1, value=dt.date.today().year, key="report_season"
        )
    with wc2:
        wk_week = st.number_input("Week", min_value=1, max_value=22, value=1, key="report_week")
    with wc3:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh odds"):
            get_odds_cached.clear()

    if st.button("Run weekly report", type="primary"):
        st.session_state.show_weekly_report = True

    if st.session_state.get("show_weekly_report"):
        report_scoreboard = live.get_scoreboard(week=int(wk_week), season=int(wk_season))
        report_games = report_scoreboard["games"]

        if not report_games:
            st.info("No games found for that week.")
        else:
            try:
                market_games, fetched_at = get_odds_cached()
                st.caption(f"Odds as of {fetched_at.strftime('%I:%M:%S %p')} (cached up to 30 min - use Refresh odds for the latest)")
            except odds_mod.OddsApiError:
                market_games = []
                if not odds_mod.get_api_key():
                    st.info(
                        "No sportsbook odds connected - showing model predictions only. See the "
                        "Matchup Predictor tab for how to add a free odds API key."
                    )

            rows = []
            week_elo_state = get_elo_state_cached(int(wk_season), int(wk_week))
            week_weekly_hist = get_weekly_hist_cached(int(wk_season), int(wk_week))
            with st.spinner("Checking weather for outdoor games..."):
                prefetch_weather_for_matchups(
                    schedules, [(g["home_team"], g["away_team"]) for g in report_games], int(wk_season), int(wk_week)
                )
            progress = st.progress(0.0, text="Running predictions...")
            for i, g in enumerate(report_games):
                home, away = g["home_team"], g["away_team"]
                pred = predict_matchup(
                    schedules, weekly, home, away, int(wk_season), int(wk_week),
                    injuries=injuries_df, elo_state=week_elo_state, weekly_hist=week_weekly_hist,
                )
                match = odds_mod.find_matchup(market_games, home, away)
                rows.append(build_report_row(pred, home, away, match))
                tracking.log_prediction(pred, int(wk_season), int(wk_week))
                progress.progress((i + 1) / len(report_games), text=f"Running predictions... {g['away_team']} @ {g['home_team']}")
            progress.empty()

            report_df = pd.DataFrame(rows)
            st.dataframe(report_df, hide_index=True, width='stretch')
            st.caption(
                "Attack notes are each team's own recent-form leaders, not a matchup-adjusted read. "
                "A market disagreement usually means missing context (injury, weather, motivation) "
                "- worth a look at the injury report on the Matchup Predictor tab."
            )

            flagged = report_df[report_df["vs. Market"] != "Market agrees"]
            flagged = flagged[flagged["vs. Market"] != "No market odds yet"]
            if not flagged.empty:
                st.caption(f"⚠️ Flagged this week: {', '.join(flagged['Matchup'])}.")

    st.divider()
    st.markdown("**Season so far**")
    st.caption(f"Every game from week 1 through week {int(wk_week)} of {int(wk_season)} - what the model called vs. what actually happened.")

    if st.button("Run season recap", type="primary"):
        st.session_state.show_season_recap = True

    if st.session_state.get("show_season_recap"):
        recap_rows = []
        progress = st.progress(0.0, text="Scoring the season so far...")
        for w in range(1, int(wk_week) + 1):
            week_board = get_scoreboard_cached(w, int(wk_season))
            if not week_board["games"]:
                continue
            w_elo_state = get_elo_state_cached(int(wk_season), w)
            w_weekly_hist = get_weekly_hist_cached(int(wk_season), w)
            # a no-op for already-played weeks (they already have real temp/wind) - only
            # the current/upcoming week actually triggers a live forecast fetch
            prefetch_weather_for_matchups(
                schedules, [(g["home_team"], g["away_team"]) for g in week_board["games"]], int(wk_season), w
            )
            for g in week_board["games"]:
                home, away = g["home_team"], g["away_team"]
                pred = predict_matchup(
                    schedules, weekly, home, away, int(wk_season), w,
                    injuries=injuries_df, elo_state=w_elo_state, weekly_hist=w_weekly_hist,
                )
                recap_rows.append(build_recap_row(pred, home, away, w, g))
            progress.progress(w / int(wk_week), text=f"Scoring week {w}...")
        progress.empty()

        if not recap_rows:
            st.info("No games found for that season yet.")
        else:
            recap_df = pd.DataFrame(recap_rows)
            st.dataframe(recap_df, hide_index=True, width='stretch')

            played = recap_df[recap_df["Model vs. actual"].isin(["Correct", "Missed"])]
            if not played.empty:
                correct = int((played["Model vs. actual"] == "Correct").sum())
                st.caption(
                    f"{correct}/{len(played)} correct ({correct / len(played):.0%}) on games played so far "
                    f"this season - each scored using only the data available before that week's kickoff."
                )

    st.divider()
    st.markdown("**Live tracking record**")
    st.caption(
        "Every real prediction made from this tab (or the weekly_report.py CLI) gets logged, then "
        "graded automatically once the real game finishes - including whether the assumed starter/"
        "featured player actually played that role, not just win/loss accuracy. See tracking.py."
    )

    if st.button("Show live tracking record"):
        st.session_state.show_tracking = True

    if st.session_state.get("show_tracking"):
        graded = tracking.grade_log(schedules, weekly)
        if not graded:
            st.info("No logged predictions have a completed real game to grade yet - run a weekly report for a real week, then check back after those games finish.")
        else:
            track_rows = []
            for g in sorted(graded, key=lambda g: (g["season"], g["week"])):
                mismatches = [k for k, ok in g["personnel_checks"].items() if not ok]
                track_rows.append(
                    {
                        "Matchup": f"{g['away_team']} @ {g['home_team']} (S{g['season']} W{g['week']})",
                        "Called": f"{g['predicted_winner']} ({g['home_win_prob']:.0%} home)",
                        "Result": "Correct" if g["winner_correct"] else "Missed",
                        "Margin (proj vs actual)": f"{g['projected_margin']:+.1f} vs {g['actual_margin']:+.0f}",
                        "Personnel mismatches": ", ".join(mismatches) if mismatches else "-",
                    }
                )
            st.dataframe(pd.DataFrame(track_rows), hide_index=True, width='stretch')

            summary = tracking.summarize(graded)
            st.caption(
                f"{summary['games']} graded games - winner accuracy {summary['accuracy']:.0%}, "
                f"Brier {summary['brier']:.4f}, mean margin error {summary['mean_margin_error']:.1f} pts."
            )
            if summary["personnel_assumption_accuracy"] is not None:
                st.caption(
                    f"Personnel-assumption accuracy: {summary['personnel_assumption_accuracy']:.0%} "
                    f"({summary['personnel_checks_total']} player-role checks) - how often the assumed "
                    f"starter/leader actually was one, per real box scores."
                )
            if summary["prop_hit_rate"] is not None:
                st.caption(f"Prop hit rate: {summary['prop_hit_rate']:.0%} (of {summary['props_graded']} gradable props - personnel mismatches excluded).")
