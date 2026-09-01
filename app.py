"""Doctor Fergie."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import chips, config, fixtures as fx, fpl_api, history, optimizer as opt, recommend, team
from src.cache import delete as cache_delete, delete_prefix as cache_delete_prefix, get_or_fetch

CACHE_MAX_AGE_SECONDS = 3600  # 1 hour
PRIOR_SEASON_CACHE_MAX_AGE_SECONDS = 90 * 24 * 3600  # completed-season stats never change

st.set_page_config(page_title="Doctor Fergie", page_icon="⚽", layout="wide")

# Premier League brand palette (2016 rebrand): deep purple, magenta, cyan, lime.
PL_PURPLE = "#3D195B"
PL_PINK = "#E90052"
PL_CYAN = "#04F5FF"
PL_GREEN = "#00FF85"

CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

.block-container {{
    padding-top: 2rem;
    max-width: 1400px;
}}

.pl-gradient-bar {{
    height: 6px;
    width: 100%;
    margin-bottom: 1.25rem;
    border-radius: 3px;
    background: linear-gradient(90deg, {PL_PURPLE}, {PL_PINK}, {PL_CYAN}, {PL_GREEN});
}}

h1, h2, h3, h4 {{
    font-family: 'Barlow Condensed', sans-serif !important;
    font-weight: 800 !important;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}}

h1 {{
    color: {PL_PINK} !important;
    margin-bottom: 0 !important;
}}

.stTabs [data-baseweb="tab-list"] {{
    gap: 0.5rem;
    flex-wrap: wrap;
}}

.stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 1.05rem;
}}

.stTabs [data-baseweb="tab-list"] button {{
    border-radius: 8px 8px 0 0;
    transition: background-color 0.15s ease;
}}

.stTabs [data-baseweb="tab-list"] button:hover {{
    background-color: rgba(233, 0, 82, 0.08);
}}

.stButton > button, .stDownloadButton > button {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    background-color: {PL_PINK};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 0.55rem 1.25rem;
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.1s ease;
}}

.stButton > button:hover, .stDownloadButton > button:hover {{
    background-color: {PL_PURPLE};
    color: {PL_CYAN};
}}

.stButton > button:active {{
    transform: scale(0.98);
}}

[data-testid="stMetric"] {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 0.85rem 1rem;
}}

[data-testid="stMetricValue"] {{
    font-family: 'Barlow Condensed', sans-serif;
    color: {PL_GREEN};
    font-weight: 800;
    font-size: 1.6rem !important;
}}

[data-testid="stMetricValue"] > div {{
    white-space: normal !important;
    overflow: hidden;
    text-overflow: clip !important;
    word-break: break-word;
    line-height: 1.2;
}}

[data-testid="stMetricLabel"] {{
    font-family: 'Inter', sans-serif;
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    opacity: 0.8;
}}

[data-testid="stExpander"] {{
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
}}

[data-testid="stDataFrame"] {{
    border-radius: 10px;
    overflow: hidden;
}}

@media (max-width: 640px) {{
    .block-container {{
        padding-left: 1rem;
        padding-right: 1rem;
        padding-top: 1.25rem;
    }}
    h1 {{
        font-size: 2.1rem !important;
    }}
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {{
        font-size: 0.9rem;
    }}
    .stButton > button, .stDownloadButton > button {{
        width: 100%;
    }}
}}

</style>
<div class="pl-gradient-bar"></div>
"""


def load_bootstrap(force_refresh=False):
    return get_or_fetch(
        "bootstrap-static",
        fpl_api.fetch_bootstrap_static,
        max_age_seconds=CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def load_fixtures(force_refresh=False):
    return get_or_fetch(
        "fixtures",
        fpl_api.fetch_fixtures,
        max_age_seconds=CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def load_entry(team_id, force_refresh=False):
    return get_or_fetch(
        f"entry:{team_id}",
        lambda: fpl_api.fetch_entry(team_id),
        max_age_seconds=CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def load_entry_history(team_id, force_refresh=False):
    return get_or_fetch(
        f"entry-history:{team_id}",
        lambda: fpl_api.fetch_entry_history(team_id),
        max_age_seconds=CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def load_entry_picks(team_id, gw, force_refresh=False):
    return get_or_fetch(
        f"entry-picks:{team_id}:{gw}",
        lambda: fpl_api.fetch_entry_picks(team_id, gw),
        max_age_seconds=CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def load_event_live(gw, force_refresh=False):
    return get_or_fetch(
        f"event-live:{gw}",
        lambda: fpl_api.fetch_event_live(gw),
        max_age_seconds=CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def load_prior_season_stats(player_ids, force_refresh=False):
    return get_or_fetch(
        "prior-season-stats",
        lambda: history.fetch_prior_season_stats(player_ids),
        max_age_seconds=PRIOR_SEASON_CACHE_MAX_AGE_SECONDS,
        force_refresh=force_refresh,
    )


def build_player_table(bootstrap):
    elements = pd.DataFrame(bootstrap["elements"])
    teams = pd.DataFrame(bootstrap["teams"])[["id", "name", "short_name"]].rename(
        columns={"id": "team", "name": "team_name", "short_name": "team_short"}
    )
    positions = pd.DataFrame(bootstrap["element_types"])[["id", "singular_name_short"]].rename(
        columns={"id": "element_type", "singular_name_short": "position"}
    )

    df = elements.merge(teams, on="team", how="left").merge(
        positions, on="element_type", how="left"
    )

    df["player"] = df["first_name"] + " " + df["second_name"]
    df["price"] = df["now_cost"] / 10.0
    numeric_cols = [
        "form",
        "points_per_game",
        "selected_by_percent",
        "ict_index",
        "chance_of_playing_next_round",
        "goals_scored",
        "assists",
        "clean_sheets",
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "saves",
        "threat",
        "creativity",
        "defensive_contribution",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[
        [
            "id",
            "team",
            "player",
            "web_name",
            "team_name",
            "team_short",
            "position",
            "price",
            "form",
            "total_points",
            "points_per_game",
            "selected_by_percent",
            "ict_index",
            "minutes",
            "status",
            "chance_of_playing_next_round",
            "goals_scored",
            "assists",
            "clean_sheets",
            "expected_goals",
            "expected_assists",
            "expected_goals_conceded",
            "saves",
            "threat",
            "creativity",
            "defensive_contribution",
        ]
    ]


STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Not eligible",
}


def format_status(row):
    label = STATUS_LABELS.get(row["status"], "Unknown")
    if row["status"] == "d" and pd.notna(row["chance_of_playing_next_round"]):
        label = f"Doubtful ({int(row['chance_of_playing_next_round'])}%)"
    return label


def render_last_updated(label, fetched_at, is_stale_fallback, error):
    fetched_at_local = fetched_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    if is_stale_fallback:
        st.warning(
            f"{label}: live refresh failed ({error}). "
            f"Showing last-known-good data from {fetched_at_local}."
        )
    else:
        st.caption(f"{label} last updated: {fetched_at_local}")


def render_players_tab(bootstrap, fixtures, fx_error, manual_refresh):
    players = build_player_table(bootstrap)

    st.subheader("Players")

    col1, col2, col3, col4 = st.columns(4, vertical_alignment="center")
    with col1:
        positions = st.multiselect(
            "Position", sorted(players["position"].dropna().unique().tolist())
        )
    with col2:
        teams_filter = st.multiselect(
            "Team", sorted(players["team_name"].dropna().unique().tolist())
        )
    with col3:
        max_price = st.slider(
            "Max price (£m)",
            min_value=float(players["price"].min()),
            max_value=float(players["price"].max()),
            value=float(players["price"].max()),
            step=0.1,
        )
    with col4:
        name_search = st.text_input("Search name")

    filtered = players.copy()
    if positions:
        filtered = filtered[filtered["position"].isin(positions)]
    if teams_filter:
        filtered = filtered[filtered["team_name"].isin(teams_filter)]
    filtered = filtered[filtered["price"] <= max_price]
    if name_search:
        filtered = filtered[filtered["player"].str.contains(name_search, case=False, na=False)]

    display_df = opt.compute_underlying_form(filtered)

    with st.spinner("Fetching last-season stats for all players (first time only)..."):
        prior_stats, _, _, _ = load_prior_season_stats(tuple(players["id"]), force_refresh=manual_refresh)
    display_df["last_season_ppg"] = pd.to_numeric(
        display_df["id"].astype(str).map(lambda i: prior_stats.get(i, {}).get("points_per_90")),
        errors="coerce",
    )
    display_df["status_label"] = display_df.apply(format_status, axis=1)

    sort_labels = {
        "total_points": "Total Points",
        "underlying_form": "Form",
        "points_per_game": "Points Per Game",
        "last_season_ppg": "Last Season PPG",
        "price": "Price",
        "selected_by_percent": "Selected By %",
        "ict_index": "ICT Index",
    }
    sort_col = st.selectbox(
        "Sort by",
        list(sort_labels),
        index=0,
        format_func=lambda c: sort_labels[c],
    )
    display_df = display_df.sort_values(sort_col, ascending=False, na_position="last")
    # Pre-formatted as text (rather than a NumberColumn) so missing values render as
    # "—" instead of Streamlit's NaN-in-NumberColumn "None" text.
    display_df["last_season_ppg_display"] = display_df["last_season_ppg"].apply(
        lambda v: f"{v:.1f}" if pd.notna(v) else "—"
    )

    display_cols = {
        "player": "Player",
        "team_name": "Team",
        "position": "Pos",
        "price": "£m",
        "underlying_form": "Form",
        "total_points": "Pts",
        "points_per_game": "PPG",
        "last_season_ppg_display": "Last Season PPG",
        "selected_by_percent": "Owned %",
        "ict_index": "ICT",
        "minutes": "Mins",
        "status_label": "Status",
    }
    st.dataframe(
        display_df[list(display_cols)].rename(columns=display_cols),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Form": st.column_config.NumberColumn(
                format="%.1f",
                help=(
                    "Points-per-90 estimate from underlying process stats: expected goals, "
                    "expected assists, clean-sheet likelihood, saves, threat/creativity "
                    "(shot/chance-creation proxies), and defensive-contribution likelihood "
                    "(tackles/interceptions/clearances) — not the same as recent points, "
                    "which can be lucky/unlucky in small samples."
                ),
            ),
            "Last Season PPG": st.column_config.TextColumn(
                help=(
                    "Points per 90 minutes last season. '—' means no qualifying prior season "
                    "(promoted-team debutant, new-to-the-league signing, or too few minutes)."
                ),
            ),
        },
    )

    st.caption(f"{len(filtered)} of {len(players)} players shown.")
    if fixtures is None:
        st.info(f"Fixtures unavailable this session: {fx_error}")


def render_fixtures_tab(bootstrap, fixtures_data, fx_error):
    if fixtures_data is None:
        st.info(f"Fixtures unavailable this session: {fx_error}")
        return

    teams_df = pd.DataFrame(bootstrap["teams"])[["id", "name", "short_name"]]
    default_start = fx.next_gameweek(bootstrap)

    st.subheader("Fixture difficulty ticker")
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        start_gw = st.number_input(
            "Starting gameweek", min_value=1, max_value=38, value=default_start
        )
    with col2:
        num_gws = st.slider("Number of gameweeks", min_value=3, max_value=8, value=5)

    display_df, difficulty_df, avg_fdr = fx.build_fixture_ticker(
        fixtures_data, teams_df, int(start_gw), int(num_gws)
    )
    st.dataframe(fx.style_ticker(display_df, difficulty_df), use_container_width=True)
    st.caption("Lower FDR (green) = easier fixture. Color scale: 1 easiest → 5 hardest.")

    st.markdown(f"#### Best & worst runs (GW{int(start_gw)}–GW{int(start_gw) + int(num_gws) - 1})")
    c1, c2 = st.columns(2, vertical_alignment="center")
    with c1:
        st.caption("Easiest average fixtures")
        best = avg_fdr.sort_values().head(5).rename("Avg FDR").to_frame()
        st.dataframe(best.style.apply(lambda s: fx.style_fdr_column(s), subset=["Avg FDR"]))
    with c2:
        st.caption("Hardest average fixtures")
        worst = avg_fdr.sort_values(ascending=False).head(5).rename("Avg FDR").to_frame()
        st.dataframe(worst.style.apply(lambda s: fx.style_fdr_column(s), subset=["Avg FDR"]))

    st.markdown("#### Fixture list")
    all_gws = sorted({f["event"] for f in fixtures_data if f.get("event")})
    gw_pick = st.selectbox("Gameweek", all_gws, index=all_gws.index(default_start) if default_start in all_gws else 0)

    team_name = dict(zip(teams_df["id"], teams_df["name"]))
    rows = []
    for f in fixtures_data:
        if f.get("event") != gw_pick:
            continue
        kickoff = f.get("kickoff_time")
        kickoff_local = (
            pd.to_datetime(kickoff, utc=True).to_pydatetime().astimezone().strftime("%a %d %b, %H:%M")
            if kickoff
            else "TBC"
        )
        score = (
            f"{f['team_h_score']}-{f['team_a_score']}"
            if f.get("finished")
            else "—"
        )
        rows.append(
            {
                "Kickoff": kickoff_local,
                "Home": team_name.get(f["team_h"], "?"),
                "FDR (H)": f["team_h_difficulty"],
                "Away": team_name.get(f["team_a"], "?"),
                "FDR (A)": f["team_a_difficulty"],
                "Score": score,
            }
        )
    fixtures_df = pd.DataFrame(rows).sort_values("Kickoff")
    st.dataframe(
        fixtures_df.style.apply(lambda s: fx.style_fdr_column(s), subset=["FDR (H)"])
        .apply(lambda s: fx.style_fdr_column(s), subset=["FDR (A)"]),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Chip timing helper")
    st.caption(
        "Wildcard: unlimited free transfers for one GW — good after a squad-wide fixture "
        "swing or an injury crisis. Free Hit: unlimited transfers for one GW only, then "
        "reverts — best saved for a blank GW. Bench Boost: your bench's points count too — "
        "best on a double GW where your whole squad plays twice. Triple Captain: captain "
        "scores 3x instead of 2x — best on a double GW or a very favourable single fixture."
    )
    chip_windows = fx.find_chip_windows(fixtures_data, teams_df, from_gw=default_start)
    if not chip_windows:
        st.info(
            "No blank or double gameweeks are currently scheduled from "
            f"GW{default_start} onward. These are usually only announced later in the "
            "season once cup-fixture reschedules are known — check back as the season "
            "progresses."
        )
    else:
        rows = []
        for w in chip_windows:
            kind = []
            if w["blank_teams"]:
                kind.append(f"Blank ({', '.join(w['blank_teams'])})")
            if w["double_teams"]:
                kind.append(f"Double ({', '.join(w['double_teams'])})")
            rows.append({"Gameweek": w["event"], "Detected": " · ".join(kind)})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_season_chart(history_df):
    fig = go.Figure()
    fig.add_bar(x=history_df["event"], y=history_df["points"], name="GW points")
    fig.add_trace(
        go.Scatter(
            x=history_df["event"],
            y=history_df["overall_rank"],
            name="Overall rank",
            yaxis="y2",
            mode="lines+markers",
        )
    )
    fig.update_layout(
        xaxis_title="Gameweek",
        yaxis=dict(title="Points"),
        yaxis2=dict(title="Overall rank", overlaying="y", side="right", autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=40, b=40),
        height=380,
    )
    return fig


def render_my_team_tab(bootstrap, players, fixtures_data, force_refresh):
    saved_team_id = config.get_team_id()

    with st.form("team_id_form", clear_on_submit=False):
        team_id_input = st.text_input(
            "FPL Team ID",
            value=str(saved_team_id) if saved_team_id else "",
            help="The number in the URL when viewing your own team's 'Points' page on the FPL site.",
        )
        submitted = st.form_submit_button("Save team ID", use_container_width=True)

    if submitted:
        team_id_input = team_id_input.strip()
        if not team_id_input.isdigit():
            st.error("Team ID must be a number.")
        else:
            candidate_id = int(team_id_input)
            try:
                fpl_api.fetch_entry(candidate_id)
            except fpl_api.FPLAPIError as e:
                st.error(f"Could not find a team with ID {candidate_id}: {e}")
            else:
                config.set_team_id(candidate_id)
                saved_team_id = candidate_id
                st.success(f"Saved team ID {candidate_id}.")

    if saved_team_id:
        if st.button("🗑️ Clear my team data", use_container_width=True):
            cache_delete(f"entry:{saved_team_id}")
            cache_delete(f"entry-history:{saved_team_id}")
            cache_delete_prefix(f"entry-picks:{saved_team_id}:")
            config.clear_team_id()
            st.success("Cleared your saved team ID and cached team data.")
            st.rerun()
        st.caption("Removes your saved team ID and any cached squad/history data for it from this machine.")

    if not saved_team_id:
        st.info("Enter your FPL team ID above to see your squad, bank, and season history.")
        return

    team_id = saved_team_id

    try:
        entry, entry_fetched_at, entry_stale, entry_error = load_entry(
            team_id, force_refresh=force_refresh
        )
        history, hist_fetched_at, hist_stale, hist_error = load_entry_history(
            team_id, force_refresh=force_refresh
        )
    except fpl_api.FPLAPIError as e:
        st.error(f"Could not load team {team_id} and no cache is available: {e}")
        return

    render_last_updated("Team info", entry_fetched_at, entry_stale, entry_error)

    next_gw = fx.next_gameweek(bootstrap)
    teams_df = pd.DataFrame(bootstrap["teams"])[["id", "short_name"]]
    next_opp_by_team = (
        fx.next_opponents_by_team(fixtures_data, teams_df, next_gw, num_opponents=1)
        if fixtures_data
        else {}
    )

    current_event = entry.get("current_event") or 1
    max_event = max(current_event, 1)
    gw = st.selectbox(
        "Gameweek",
        list(range(1, max_event + 1)),
        index=max_event - 1,
    )

    try:
        picks, picks_fetched_at, picks_stale, picks_error = load_entry_picks(
            team_id, gw, force_refresh=force_refresh
        )
    except fpl_api.FPLAPIError as e:
        st.error(f"Could not load picks for GW{gw}: {e}")
        return

    try:
        live, _, _, _ = load_event_live(gw, force_refresh=force_refresh)
    except fpl_api.FPLAPIError:
        live = None

    gw_info = picks["entry_history"]

    st.subheader(f"{entry.get('name', 'My team')} — {entry.get('player_first_name', '')} {entry.get('player_last_name', '')}")

    m1, m2, m3, m4, m5 = st.columns(5, vertical_alignment="center")
    m1.metric("Overall points", entry.get("summary_overall_points"))
    m2.metric("Overall rank", f"{entry.get('summary_overall_rank'):,}" if entry.get("summary_overall_rank") else "—")
    m3.metric(f"GW{gw} points", gw_info.get("points"))
    m4.metric("Bank", f"£{gw_info.get('bank', 0) / 10:.1f}m")
    m5.metric("Squad value", f"£{gw_info.get('value', 0) / 10:.1f}m")

    free_transfers = team.estimate_free_transfers(history)
    active_chip = picks.get("active_chip")
    c1, c2 = st.columns(2, vertical_alignment="center")
    c1.metric("Free transfers (estimated)", free_transfers)
    c2.metric("Active chip this GW", active_chip or "None")

    chips_used = history.get("chips", [])
    if chips_used:
        st.caption(
            "Chips used: "
            + ", ".join(f"{c['name']} (GW{c['event']})" for c in chips_used)
        )
    else:
        st.caption("No chips used yet this season.")

    st.markdown("#### Squad")
    squad_df = team.build_squad_df(picks, players, live=live)
    squad_df["next_opp"] = squad_df["team"].map(next_opp_by_team).fillna("—")
    display_cols = {
        "web_name": "Player",
        "team_short": "Team",
        "position": "Pos",
        "price": "£m",
        "role": "",
        "gw_points": "Pts",
        "multiplier": "x",
        "effective_points": "Total",
        "next_opp": "Next",
    }
    starters = squad_df[squad_df["is_starting"]]
    bench = squad_df[~squad_df["is_starting"]]
    st.dataframe(
        starters[list(display_cols)].rename(columns=display_cols),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Bench")
    st.dataframe(
        bench[list(display_cols)].rename(columns=display_cols),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(f"#### Ideal XI for next gameweek (GW{next_gw})")
    st.caption(
        "Best starting XI from your actual 15-man squad for the upcoming gameweek — "
        "form/PPG adjusted for that gameweek's specific fixture (a blank scores 0, a "
        "double counts both fixtures). Not a transfer suggestion, just the best way to "
        "line up what you already own."
    )
    if fixtures_data is None:
        st.info("Fixtures unavailable this session — can't factor in fixture difficulty.")
    else:
        try:
            current_picks, _, _, _ = load_entry_picks(team_id, current_event, force_refresh=force_refresh)
        except fpl_api.FPLAPIError as e:
            st.error(f"Could not load your current squad: {e}")
            current_picks = None

        if current_picks is not None:
            current_ids = [p["element"] for p in current_picks["picks"]]
            ranked = recommend.recommend_captain(current_ids, players, fixtures_data, next_gw)
            ranked["next_opp"] = ranked["team"].map(next_opp_by_team).fillna("—")
            result = opt.best_starting_xi(ranked, score_col="expected_score") if not ranked.empty else None
            if result is None:
                st.info("Couldn't determine an ideal XI for the next gameweek.")
            else:
                ideal_starting_ids, ideal_bench_ids, ideal_formation = result
                ideal_starters = ranked[ranked["id"].isin(ideal_starting_ids)].sort_values(
                    "expected_score", ascending=False
                )
                ideal_bench = ranked[ranked["id"].isin(ideal_bench_ids)].sort_values(
                    "expected_score", ascending=False
                )

                cap, vice = opt.pick_captain_vice(ideal_starters, score_col="expected_score")
                im1, im2 = st.columns(2, vertical_alignment="center")
                im1.metric("Ideal formation", ideal_formation)
                im2.metric("Expected score (XI)", f"{ideal_starters['expected_score'].sum():.1f}")
                label = f"**Suggested captain: {cap['web_name']}**"
                if vice is not None:
                    label += f" · Vice: {vice['web_name']}"
                st.markdown(label)

                actual_starting_ids = {p["element"] for p in current_picks["picks"] if p["position"] <= 11}
                bench_to_start = ideal_starting_ids - actual_starting_ids
                start_to_bench = actual_starting_ids - ideal_starting_ids
                if bench_to_start or start_to_bench:
                    id_to_name = dict(zip(players["id"], players["web_name"]))
                    start_names = ", ".join(id_to_name.get(i, "?") for i in bench_to_start)
                    bench_names = ", ".join(id_to_name.get(i, "?") for i in start_to_bench)
                    st.warning(
                        f"Differs from your currently set lineup — consider starting "
                        f"**{start_names}** instead of **{bench_names}**."
                    )
                else:
                    st.success("Your currently set lineup already matches this suggestion.")

                ideal_display_cols = {
                    "web_name": "Player",
                    "team_name": "Team",
                    "position": "Pos",
                    "next_opp": "Next",
                    "expected_score": "Expected",
                }
                st.dataframe(
                    ideal_starters[list(ideal_display_cols)].rename(columns=ideal_display_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config={"Expected": st.column_config.NumberColumn(format="%.1f")},
                )
                st.caption("Bench")
                st.dataframe(
                    ideal_bench[list(ideal_display_cols)].rename(columns=ideal_display_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config={"Expected": st.column_config.NumberColumn(format="%.1f")},
                )

    st.markdown("#### Captain recommendation")
    st.caption(
        f"Ranks your GW{gw} starting XI by expected score: recent form/PPG adjusted for "
        "that gameweek's fixture difficulty (a blank gameweek scores 0, a double gameweek "
        "counts both fixtures). A simple proxy, not a real forecast."
    )
    if fixtures_data is None:
        st.info("Fixtures unavailable this session — can't factor in fixture difficulty.")
    else:
        starter_ids = starters["element"].tolist()
        ranked = recommend.recommend_captain(starter_ids, players, fixtures_data, gw)
        if ranked.empty:
            st.info("No starting XI found for this gameweek.")
        else:
            opp_by_team_for_gw = fx.next_opponents_by_team(fixtures_data, teams_df, gw, num_opponents=1)
            ranked["next_opp"] = ranked["team"].map(opp_by_team_for_gw).fillna("—")
            top, vice = opt.pick_captain_vice(ranked, score_col="expected_score")
            label = f"**Suggested captain: {top['web_name']}**"
            if vice is not None:
                label += f" · Vice: {vice['web_name']}"
            st.markdown(label)
            display = ranked.rename(
                columns={
                    "web_name": "Player",
                    "team_short": "Team",
                    "fixture_count": "Fixtures",
                    "next_opp": "Next",
                    "score": "Season score",
                    "expected_score": "Expected (this GW)",
                }
            )
            st.dataframe(
                display[["Player", "Team", "Next", "Fixtures", "Season score", "Expected (this GW)"]],
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("#### Chip strategy")
    st.caption(
        "Personalized suggestions from your actual squad, current form, and fixtures — not "
        "just blank/double gameweek detection. Same 'simple proxy, not a real forecast' "
        "caveat as the rest of this app applies, more so this early in the season when form "
        "and points-per-game have few games to draw on."
    )
    available_chips = chips.available_chips(bootstrap, chips_used, next_gw)
    if fixtures_data is None:
        st.info("Fixtures unavailable this session — can't compute chip suggestions.")
    else:
        try:
            chip_picks, _, _, _ = load_entry_picks(team_id, current_event, force_refresh=force_refresh)
        except fpl_api.FPLAPIError as e:
            st.error(f"Could not load your current squad: {e}")
            chip_picks = None

        if chip_picks is not None:
            chip_current_ids = [p["element"] for p in chip_picks["picks"]]
            chip_ranked_next = recommend.recommend_captain(chip_current_ids, players, fixtures_data, next_gw)
            chip_xi = (
                opt.best_starting_xi(chip_ranked_next, score_col="expected_score")
                if not chip_ranked_next.empty
                else None
            )

            cols = st.columns(4)

            with cols[0]:
                st.markdown("**Bench Boost**")
                bb = None
                if chip_xi is not None:
                    starting_ids, bench_ids, _ = chip_xi
                    ideal_starters = chip_ranked_next[chip_ranked_next["id"].isin(starting_ids)]
                    ideal_bench = chip_ranked_next[chip_ranked_next["id"].isin(bench_ids)]
                    bb = chips.suggest_bench_boost(ideal_starters, ideal_bench)
                if not available_chips.get("bboost"):
                    st.caption("Already used / not available this window.")
                elif bb is None:
                    st.caption("Not enough data.")
                elif bb["recommend"]:
                    st.success(
                        f"Good week — bench projects {bb['bench_total']:.1f} pts "
                        f"(avg {bb['bench_avg']:.1f} vs starters' {bb['starter_avg']:.1f})."
                    )
                else:
                    st.info(
                        f"Save it — bench projects only {bb['bench_total']:.1f} pts "
                        f"(avg {bb['bench_avg']:.1f} vs starters' {bb['starter_avg']:.1f})."
                    )

            with cols[1]:
                st.markdown("**Triple Captain**")
                tc = None
                if chip_xi is not None:
                    starting_ids, _, _ = chip_xi
                    ideal_starters = chip_ranked_next[chip_ranked_next["id"].isin(starting_ids)]
                    cap, _ = opt.pick_captain_vice(ideal_starters, score_col="expected_score")
                    tc = chips.suggest_triple_captain(cap)
                if not available_chips.get("3xc"):
                    st.caption("Already used / not available this window.")
                elif tc is None:
                    st.caption("Not enough data.")
                elif tc["recommend"]:
                    reason = "double gameweek" if tc["is_double"] else "strong fixture"
                    st.success(
                        f"Good week — {tc['captain_name']} projects {tc['captain_score']:.1f} "
                        f"pts ({reason})."
                    )
                else:
                    st.info(
                        f"Save it — best captain ({tc['captain_name']}) only projects "
                        f"{tc['captain_score']:.1f} pts."
                    )

            bank = chip_picks["entry_history"].get("bank", 0) / 10.0
            value = chip_picks["entry_history"].get("value", 0) / 10.0
            reset = chips.suggest_reset_chip(
                players, chip_current_ids, fixtures_data, next_gw, budget=bank + value
            )

            with cols[2]:
                st.markdown("**Free Hit**")
                if not available_chips.get("freehit"):
                    st.caption("Already used / not available this window.")
                elif reset["recommend_freehit"]:
                    st.success(
                        f"Consider it — an optimal squad projects {reset['gap_next_gw'] * 100:.0f}% "
                        f"higher ({reset['optimal_next_gw']:.1f} vs {reset['current_next_gw']:.1f} pts) "
                        "just for this gameweek, and that gap doesn't persist over the coming weeks."
                    )
                elif reset["gap_next_gw"] >= chips.FREEHIT_GAP_THRESHOLD:
                    st.info(
                        "Save it — this gameweek's gap is real, but it doesn't go away next week "
                        "either, so Wildcard fixes it better than a one-week Free Hit."
                    )
                else:
                    st.info(
                        f"Save it — only a {reset['gap_next_gw'] * 100:.0f}% gap to an optimal squad "
                        "this gameweek."
                    )

            with cols[3]:
                st.markdown("**Wildcard**")
                if not available_chips.get("wildcard"):
                    st.caption("Already used / not available this window.")
                elif reset["recommend_wildcard"]:
                    st.success(
                        f"Consider it — your squad projects {reset['gap_lookahead'] * 100:.0f}% below "
                        f"an optimal one ({reset['optimal_lookahead']:.1f} vs "
                        f"{reset['current_lookahead']:.1f} pts) over the next {reset['lookahead_gws']} "
                        "gameweeks, not just a one-off."
                    )
                else:
                    st.info(
                        f"Save it — only a {reset['gap_lookahead'] * 100:.0f}% gap to an optimal squad "
                        f"over the next {reset['lookahead_gws']} gameweeks."
                    )

    st.markdown("#### Season history")
    history_df = team.build_season_history_df(history)
    if not history_df.empty:
        st.plotly_chart(render_season_chart(history_df), use_container_width=True)
    else:
        st.info("No completed gameweeks yet this season.")


SCORE_CAVEAT = (
    "Scores are a simple proxy (recent form + points-per-game), not a real points "
    "forecast — early in the season this is especially noisy since 'form' has few "
    "games to draw on. Treat suggestions as a starting point, not gospel."
)


def render_squad_table(squad_df, caption, next_opponents=None):
    display_cols = {
        "web_name": "Player",
        "team_name": "Team",
        "position": "Pos",
        "price": "£m",
        "score": "Score",
        "role": "",
    }
    df = squad_df.copy()
    if next_opponents is not None:
        df["next_3"] = df["team"].map(next_opponents).fillna("—")
        display_cols["next_3"] = "Next 3"
    st.caption(caption)
    st.dataframe(
        df[list(display_cols)].rename(columns=display_cols),
        use_container_width=True,
        hide_index=True,
    )


def render_optimizer_tab(bootstrap, players, fixtures_data, force_refresh):
    st.subheader("Build a best-XI squad from scratch")
    st.caption(SCORE_CAVEAT)

    default_start_gw = fx.next_gameweek(bootstrap)
    teams_df = pd.DataFrame(bootstrap["teams"])[["id", "short_name"]]
    next_opponents = (
        fx.next_opponents_by_team(fixtures_data, teams_df, default_start_gw) if fixtures_data else {}
    )

    col1, col2, col3 = st.columns(3, vertical_alignment="center")
    with col1:
        budget = st.number_input("Budget (£m)", min_value=80.0, max_value=100.0, value=100.0, step=0.5)
    with col2:
        exclude_unavailable = st.checkbox("Exclude injured/suspended players", value=True)
    with col3:
        formation_choice = st.selectbox(
            "Formation", ["Auto (best-scoring)"] + opt.VALID_FORMATIONS
        )
    formation = None if formation_choice == "Auto (best-scoring)" else formation_choice

    with st.expander("Advanced: score weighting"):
        form_weight = st.slider("Weight on recent form", 0.0, 1.0, 0.7, 0.1)
        budget_weight = st.slider("Weight on full budget utilization", 0.0, 1.0, 0.0, 0.1)
        st.caption(
            "0 = spend only what buys extra score, leaving money unspent if it doesn't help. "
            "Higher values increasingly reward using up the full budget, even trading a little "
            "score for pricier players once cheaper ones score about the same."
        )
        fc1, fc2 = st.columns(2, vertical_alignment="center")
        with fc1:
            fixture_weight = st.slider("Weight on fixture difficulty", 0.0, 1.0, 0.5, 0.1)
        with fc2:
            lookahead_gws = st.number_input(
                "Gameweeks to look ahead", min_value=1, max_value=8, value=5
            )
        st.caption(
            f"0 = ignore fixtures entirely (score is season form/PPG only). Higher values "
            f"increasingly favour players whose team has an easy run over the next "
            f"{lookahead_gws} gameweek(s) starting GW{default_start_gw} — a double gameweek "
            "boosts a player's score, a blank zeroes it out for that stretch."
        )
        last_season_weight = st.slider("Weight on last season's performance", 0.0, 1.0, 0.3, 0.1)
        st.caption(
            "0 = ignore last season entirely. Higher values blend in each player's points-per-90 "
            "from their last completed season — a stabilizer against thin in-season form/PPG "
            "samples, especially early on. Promoted-team debutants, new-to-the-league signings, "
            "and fringe players with too few minutes last season are left as-is (judged on this "
            "season only, since there's no prior season to draw on). The first use fetches this "
            "for every player (~10-15s, one-time); it's cached after that."
        )

    def score_with_all_adjustments(players_df):
        scored = opt.compute_score(players_df, form_weight=form_weight, ppg_weight=1 - form_weight)
        if last_season_weight > 0:
            with st.spinner("Fetching last-season stats for all players (first time only)..."):
                prior_stats, _, _, _ = load_prior_season_stats(tuple(players_df["id"]))
            scored = opt.apply_last_season_adjustment(scored, prior_stats, weight=last_season_weight)
        scored = opt.apply_fixture_adjustment(
            scored, fixtures_data, default_start_gw, int(lookahead_gws), fixture_weight=fixture_weight
        )
        return scored

    if st.button("Run optimizer", use_container_width=True):
        scored = score_with_all_adjustments(players)
        squad_df = opt.optimize_squad(
            scored,
            budget=budget,
            exclude_unavailable=exclude_unavailable,
            formation=formation,
            budget_weight=budget_weight,
        )
        if squad_df is None:
            st.error("No feasible squad found under these constraints (try a higher budget).")
        else:
            starters = squad_df[squad_df["is_starting"]]
            bench = squad_df[~squad_df["is_starting"]]
            m1, m2, m3 = st.columns(3, vertical_alignment="center")
            m1.metric("Formation", opt.formation_label(squad_df))
            m2.metric("Squad cost", f"£{squad_df['price'].sum():.1f}m")
            m3.metric("Predicted score (XI)", f"{starters['score'].sum():.1f}")
            render_squad_table(starters, "Starting XI (C = captain, VC = vice-captain)", next_opponents)
            render_squad_table(bench, "Bench", next_opponents)

    st.divider()
    st.subheader("Suggest transfers for my team")
    st.caption("Uses the same form/fixture weighting settings as the squad builder above.")

    team_id = config.get_team_id()
    if not team_id:
        st.info("Save your FPL team ID in the 'My Team' tab first to get transfer suggestions.")
        return

    try:
        entry, _, _, _ = load_entry(team_id, force_refresh=force_refresh)
        entry_history, _, _, _ = load_entry_history(team_id, force_refresh=force_refresh)
    except fpl_api.FPLAPIError as e:
        st.error(f"Could not load your team: {e}")
        return

    current_event = entry.get("current_event") or 1
    try:
        picks, _, _, _ = load_entry_picks(team_id, current_event, force_refresh=force_refresh)
    except fpl_api.FPLAPIError as e:
        st.error(f"Could not load your current squad: {e}")
        return

    current_ids = [p["element"] for p in picks["picks"]]
    bank = picks["entry_history"].get("bank", 0) / 10.0
    free_transfers = team.estimate_free_transfers(entry_history)

    c1, c2 = st.columns(2, vertical_alignment="center")
    c1.metric("Bank", f"£{bank:.1f}m")
    c2.metric("Free transfers (estimated)", free_transfers)

    num_transfers = st.slider("Number of transfers to suggest", 1, 5, min(free_transfers, 5))

    if st.button("Suggest transfers", use_container_width=True):
        scored = score_with_all_adjustments(players)
        suggestions = opt.suggest_transfers(
            current_ids, scored, bank=bank, num_transfers=num_transfers, free_transfers=free_transfers
        )
        if not suggestions:
            st.info("No improving transfer found — your squad already looks strong by this proxy.")
        else:
            for i, s in enumerate(suggestions, start=1):
                hit_label = " (hit: -4 pts)" if s["is_hit"] else " (free)"
                st.markdown(
                    f"**{i}. OUT:** {s['out_name']} ({s['out_team']}, £{s['out_price']:.1f}m) "
                    f"→ **IN:** {s['in_name']} ({s['in_team']}, £{s['in_price']:.1f}m){hit_label}"
                )
                st.caption(
                    f"Score gain: +{s['score_gain']:.1f} · Net after hit: {s['net_gain']:+.1f} · "
                    f"Cost change: £{s['cost_delta']:+.1f}m"
                )
            total_net = sum(s["net_gain"] for s in suggestions)
            st.metric("Total net score gain", f"{total_net:+.1f}")


st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Auto-refresh once per new browser session/page load (not on every widget
# rerun — that would hammer the FPL API on every filter click).
if "did_initial_refresh" not in st.session_state:
    st.session_state.did_initial_refresh = True
    auto_refresh = True
else:
    auto_refresh = False

title_col, refresh_col = st.columns([5, 1], vertical_alignment="center")
with title_col:
    st.title("Doctor Fergie")
with refresh_col:
    manual_refresh = st.button("🔄 Refresh", use_container_width=True)

force_refresh = auto_refresh or manual_refresh

try:
    bootstrap, bs_fetched_at, bs_stale, bs_error = load_bootstrap(force_refresh=force_refresh)
except fpl_api.FPLAPIError as e:
    st.error(f"Could not load FPL data and no cache is available: {e}")
    st.stop()

try:
    fixtures, fx_fetched_at, fx_stale, fx_error = load_fixtures(force_refresh=force_refresh)
except fpl_api.FPLAPIError as e:
    fixtures, fx_fetched_at, fx_stale, fx_error = None, None, False, str(e)

render_last_updated("Player data", bs_fetched_at, bs_stale, bs_error)
if fixtures is not None:
    render_last_updated("Fixtures", fx_fetched_at, fx_stale, fx_error)

players = build_player_table(bootstrap)

tab_players, tab_fixtures, tab_my_team, tab_optimizer = st.tabs(
    ["Players", "Fixtures", "My Team", "Optimizer"]
)
with tab_players:
    render_players_tab(bootstrap, fixtures, fx_error, manual_refresh)
with tab_fixtures:
    render_fixtures_tab(bootstrap, fixtures, fx_error)
with tab_my_team:
    render_my_team_tab(bootstrap, players, fixtures, force_refresh)
with tab_optimizer:
    render_optimizer_tab(bootstrap, players, fixtures, force_refresh)
