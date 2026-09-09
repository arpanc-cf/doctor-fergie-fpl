"""Doctor Fergie."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import chips, config, fixtures as fx, fpl_api, history, optimizer as opt, recommend, team
from src.cache import delete as cache_delete, delete_prefix as cache_delete_prefix, get_or_fetch

CACHE_MAX_AGE_SECONDS = 3600  # 1 hour
PRIOR_SEASON_CACHE_MAX_AGE_SECONDS = 90 * 24 * 3600  # completed-season stats never change

st.set_page_config(page_title="Doctor Fergie", page_icon="⚽", layout="wide")

# Premier League's actual current brand system (2023 "Modern Warrior"
# rebrand, sampled from premierleague.com's own stylesheet): a near-black
# purple tonal scale carries the whole site, with pink used only as a
# sparing accent — not the loud 2016-era purple/pink/cyan/green foursome
# this file used to hardcode.
PL_PURPLE = "#37003C"  # their signature brand purple (widget/surface fills)
PL_BG = "#1E0021"  # page background
PL_SURFACE = "#28002B"  # card/table surface, one step up from the page
PL_SURFACE_HI = "#41054B"  # hover/elevated surface, two steps up
PL_PINK = "#FF2882"  # their actual accent pink — used sparingly, not as a fill color

# The FPL API returns chip identifiers as internal codes (lowercase,
# abbreviated), not display-ready names.
CHIP_DISPLAY_NAMES = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
}


def chip_display_name(code):
    return CHIP_DISPLAY_NAMES.get(code, code.replace("_", " ").title()) if code else None


CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* premierleague.com runs one typeface throughout (their own "PremierLeague"
   cut, bold for headings) rather than pairing a display face with a body
   face — Inter at varying weight mirrors that single-family approach,
   since their font isn't licensed for embedding here. */
html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

.stApp {{
    background-color: {PL_BG};
    background-image:
        radial-gradient(ellipse 1000px 600px at 15% -10%, rgba(55, 0, 60, 0.7), transparent 60%);
    background-attachment: fixed;
}}

.block-container {{
    padding-top: 1.75rem;
    max-width: 1400px;
}}

.pl-gradient-bar {{
    height: 3px;
    width: 100%;
    margin-bottom: 1.5rem;
    border-radius: 3px;
    background: linear-gradient(90deg, {PL_PURPLE}, {PL_PINK});
}}

/* No uppercase, no wide tracking — their real headings are bold-weight
   Inter-like text at (slightly) negative letter-spacing, not condensed
   display caps. */
h1, h2, h3, h4 {{
    font-family: 'Inter', sans-serif !important;
    font-weight: 800 !important;
    letter-spacing: -0.01em;
}}

h1 {{
    color: {PL_PINK} !important;
    margin-bottom: 0 !important;
}}

h4 {{
    padding-top: 0.4rem;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
}}

hr {{
    border: none !important;
    height: 1px !important;
    background: linear-gradient(90deg, rgba(255, 40, 130, 0.4), transparent) !important;
    margin: 1.1rem 0 !important;
}}

.stTabs [data-baseweb="tab-list"] {{
    gap: 0.5rem;
    flex-wrap: wrap;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}}

.stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {{
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    font-size: 0.95rem;
}}

.stTabs [data-baseweb="tab-list"] button {{
    border-radius: 8px 8px 0 0;
    transition: background-color 0.15s ease;
}}

.stTabs [data-baseweb="tab-list"] button:hover {{
    background-color: rgba(255, 40, 130, 0.08);
}}

.stTabs [data-baseweb="tab-highlight"] {{
    background-color: {PL_PINK} !important;
}}

/* Pill-shaped, moderate weight, sentence case — matches the "Sign in" /
   "Join myPL" buttons on the real site rather than a bold uppercase CTA
   block. */
.stButton > button, .stDownloadButton > button {{
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    background-color: {PL_PURPLE};
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 999px;
    padding: 0.5rem 1.3rem;
    white-space: nowrap;
    transition: background-color 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
}}

.stButton > button:hover, .stDownloadButton > button:hover {{
    background-color: {PL_SURFACE_HI};
    border-color: {PL_PINK};
    color: white;
}}

.stButton > button:active {{
    transform: scale(0.98);
}}

/* Flat filled inputs get a hairline border and a soft focus ring, so they
   read as distinct fields instead of solid blocks. */
[data-baseweb="select"] > div,
.stTextInput input,
.stNumberInput input {{
    background-color: {PL_SURFACE} !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}}

[data-baseweb="select"]:focus-within > div,
.stTextInput input:focus,
.stNumberInput input:focus {{
    border-color: rgba(255, 40, 130, 0.6) !important;
    box-shadow: 0 0 0 3px rgba(255, 40, 130, 0.15) !important;
}}

[data-testid="stMetric"] {{
    position: relative;
    background: linear-gradient(160deg, {PL_SURFACE_HI} 0%, {PL_SURFACE} 65%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 0.95rem 1.1rem;
    transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}}

/* A thin brand-gradient cap on every stat card — the "stand out" cue
   that ties them together as a distinct row of headline numbers. Its own
   rounded top corners (matching the card's) stand in for overflow:hidden
   on the card, which would otherwise clip a label that wraps to 2 lines. */
[data-testid="stMetric"]::before {{
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    border-radius: 14px 14px 0 0;
    background: linear-gradient(90deg, {PL_PINK}, {PL_PURPLE});
}}

[data-testid="stMetric"]:hover {{
    transform: translateY(-3px);
    border-color: rgba(255, 40, 130, 0.4);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.4);
}}

[data-testid="stMetricValue"] {{
    font-family: 'Inter', sans-serif;
    color: white;
    font-weight: 800;
    font-size: 1.7rem !important;
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
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    opacity: 0.7;
}}

/* Streamlit's own metric label defaults to a single line with an
   ellipsis — fine for a short label, but "Overall points" in a narrow
   column (especially with a help-tooltip icon eating into it) just reads
   as "Overall...". Let it wrap onto a second line instead of truncating. */
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] [data-testid="stMarkdownContainer"],
[data-testid="stMetricLabel"] > div {{
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
}}

/* Delta reads as a small ticker chip rather than plain colored text. */
[data-testid="stMetricDelta"] {{
    font-family: 'Inter', sans-serif;
    font-weight: 700;
    font-size: 0.82rem;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    width: fit-content;
    margin-top: 0.15rem;
}}

/* A hand-built stat card matching stMetric's look, for cases (like an
   active-chip indicator) that need a state st.metric can't express —
   here, a highlighted variant for "something is actively happening". */
.pl-stat-row {{
    display: flex;
    gap: 1rem;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
}}

.pl-stat-card {{
    position: relative;
    flex: 1;
    min-width: 160px;
    background: linear-gradient(160deg, {PL_SURFACE_HI} 0%, {PL_SURFACE} 65%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 0.95rem 1.1rem;
}}

.pl-stat-card::before {{
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    border-radius: 14px 14px 0 0;
    background: linear-gradient(90deg, {PL_PINK}, {PL_PURPLE});
}}

.pl-stat-card--active {{
    background: linear-gradient(160deg, rgba(255, 40, 130, 0.3) 0%, {PL_SURFACE} 75%);
    border-color: rgba(255, 40, 130, 0.55);
    box-shadow: 0 0 0 1px rgba(255, 40, 130, 0.2), 0 8px 22px rgba(255, 40, 130, 0.18);
}}

.pl-stat-card--active::before {{
    background: {PL_PINK};
    box-shadow: 0 0 12px rgba(255, 40, 130, 0.7);
}}

.pl-stat-label {{
    font-family: 'Inter', sans-serif;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    opacity: 0.7;
    margin-bottom: 0.3rem;
}}

.pl-stat-value {{
    font-family: 'Inter', sans-serif;
    color: white;
    font-weight: 800;
    font-size: 1.7rem;
    line-height: 1.2;
}}

.pl-stat-badge {{
    display: inline-block;
    margin-top: 0.4rem;
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: {PL_PINK};
    background: rgba(255, 40, 130, 0.15);
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
}}

/* A native-tooltip "?" affordance for the hand-built stat cards, echoing
   st.metric's own help-icon treatment elsewhere on the page. */
.pl-stat-help {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin-left: 0.35rem;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.35);
    font-size: 0.65rem;
    font-weight: 700;
    opacity: 0.6;
    cursor: help;
    vertical-align: middle;
}}

[data-testid="stExpander"] {{
    background: {PL_SURFACE};
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
}}

/* The dataframe grid renders to <canvas>, which reads this custom
   property for its own font rather than inheriting page CSS — without
   it, table text quietly falls back to Streamlit's default ("Source
   Sans"), out of step with the Inter used everywhere else. */
[data-testid="stDataFrame"] {{
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.06);
    --gdg-font-family: 'Inter', sans-serif;
}}

/* Success/info/warning callouts: a subtle left accent instead of a flat
   tinted block on all four sides. */
[data-testid="stAlertContainer"] {{
    border-radius: 10px;
    border-left-width: 3px !important;
    border-left-style: solid !important;
}}

/* Wider than the phone breakpoint below: covers the awkward zone where
   Streamlit keeps title/action columns side by side but the action
   column is too narrow for its label not to wrap mid-word. */
@media (max-width: 780px) {{
    .stButton > button, .stDownloadButton > button {{
        width: 100%;
    }}
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
    /* At phone widths the four tab labels no longer fit on one row.
       flex-wrap would push the overflow tab onto a second row, which
       throws off BaseWeb's absolutely-positioned active-tab underline
       (it ends up under the wrong row). A single scrollable row keeps
       the underline correct and is a more familiar mobile tab pattern
       anyway — swipe to see the rest. */
    .stTabs [data-baseweb="tab-list"] {{
        flex-wrap: nowrap;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }}
    .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {{
        display: none;
    }}
    .stTabs [data-baseweb="tab-list"] button {{
        flex: 0 0 auto;
    }}
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {{
        font-size: 0.9rem;
        white-space: nowrap;
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


def load_entry_transfers(team_id, force_refresh=False):
    return get_or_fetch(
        f"entry-transfers:{team_id}",
        lambda: fpl_api.fetch_entry_transfers(team_id),
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


def _signed_gbp(value):
    """Format a £m delta with the sign as the very first character (e.g.
    "+£0.5m", "-£0.2m") — st.metric's delta color/arrow only reads the
    sign correctly when it leads the string, not when a currency symbol
    comes first.
    """
    sign = "+" if value >= 0 else "-"
    return f"{sign}£{abs(value):.1f}m"


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
        font=dict(family="Inter, sans-serif"),
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
    latest_deltas = team.gw_over_gw_deltas(history, current_event)
    gw_deltas = team.gw_over_gw_deltas(history, gw)

    st.subheader(f"{entry.get('name', 'My team')} — {entry.get('player_first_name', '')} {entry.get('player_last_name', '')}")

    m1, m2, m3, m4, m5 = st.columns(5, vertical_alignment="center")
    m1.metric(
        "Overall points",
        entry.get("summary_overall_points"),
        delta=gw_info.get("points"),
        help="Change = points scored this gameweek.",
    )
    m2.metric(
        "Overall rank",
        f"{entry.get('summary_overall_rank'):,}" if entry.get("summary_overall_rank") else "—",
        delta=f"{latest_deltas['overall_rank_delta']:,}" if latest_deltas else None,
        help="Change vs the previous gameweek (positive = moved up).",
    )
    m3.metric(
        f"GW{gw} points",
        gw_info.get("points"),
        delta=gw_deltas["points_delta"] if gw_deltas else None,
        help="Change vs the previous gameweek's points.",
    )
    m4.metric(
        "Bank",
        f"£{gw_info.get('bank', 0) / 10:.1f}m",
        # The sign has to be the very first character or Streamlit's delta
        # color/arrow logic misreads it — "£-0.2m" reads as positive.
        delta=_signed_gbp(gw_deltas["bank_delta"]) if gw_deltas else None,
        help="Change vs the previous gameweek.",
    )
    m5.metric(
        "Squad value",
        f"£{gw_info.get('value', 0) / 10:.1f}m",
        delta=_signed_gbp(gw_deltas["value_delta"]) if gw_deltas else None,
        help="Change vs the previous gameweek.",
    )

    free_transfers = team.estimate_free_transfers(history)
    active_chip = picks.get("active_chip")
    active_chip_label = f"Used ({chip_display_name(active_chip)})" if active_chip else "Not Used"
    active_card_class = "pl-stat-card pl-stat-card--active" if active_chip else "pl-stat-card"
    active_badge = '<div class="pl-stat-badge">● Active</div>' if active_chip else ""
    # st.markdown treats 4+ leading spaces as a Markdown code block, so this
    # has to be built with no line-leading indentation or it renders as a
    # broken mix of raw HTML and literal code-block text.
    free_transfers_help = (
        "FPL does not expose free transfers remaining directly, so this is "
        "a best-effort estimate from your transfer history, not guaranteed "
        "accurate."
    )
    stat_row_html = (
        '<div class="pl-stat-row">'
        '<div class="pl-stat-card">'
        '<div class="pl-stat-label">Free transfers'
        f'<span class="pl-stat-help" title="{free_transfers_help}">?</span>'
        "</div>"
        f'<div class="pl-stat-value">{free_transfers}</div>'
        "</div>"
        f'<div class="{active_card_class}">'
        '<div class="pl-stat-label">Active chip this GW</div>'
        f'<div class="pl-stat-value">{active_chip_label}</div>'
        f"{active_badge}"
        "</div>"
        "</div>"
    )
    st.markdown(stat_row_html, unsafe_allow_html=True)

    chips_used = history.get("chips", [])
    if chips_used:
        st.caption(
            "Chips used: "
            + ", ".join(f"{chip_display_name(c['name'])} (GW{c['event']})" for c in chips_used)
        )
    else:
        st.caption("No chips used yet this season.")

    st.markdown("#### Squad")
    squad_df = team.build_squad_df(picks, players, live=live)
    squad_df["next_opp"] = squad_df["team"].map(next_opp_by_team).fillna("—")
    squad_df["display_name"] = squad_df["web_name"] + squad_df["role"].map(
        {"C": " (C)", "VC": " (VC)"}
    ).fillna("")
    display_cols = {
        "display_name": "Player",
        "team_name": "Team",
        "position": "Pos",
        "price": "£m",
        "gw_points": "Pts",
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

    if gw == current_event:
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

                    st.markdown("#### Transfer Matrix")
                    st.caption(
                        "Suggest transfers against your actual squad and see the resulting "
                        "Ideal XI for next gameweek. Nothing below runs until you turn on a "
                        "toggle or move the slider."
                    )
                    toggle_col1, toggle_col2 = st.columns(2)
                    with toggle_col1:
                        auto_maximize_transfers = st.toggle(
                            "Maximize potential score",
                            help="Overrides the slider below — checks every transfer count "
                            "from 0 up to 5, subtracts 4 points for each one beyond your free "
                            "transfers, and uses whichever count gives the highest net "
                            "expected score for this gameweek.",
                        )
                    with toggle_col2:
                        maximize_budget_transfers = st.toggle(
                            "Maximize budget utilization",
                            help="Among transfers that genuinely improve your expected score "
                            "(never a downgrade), picks the most expensive affordable "
                            "option your bank allows, using expected score to choose "
                            "between similarly-priced options. The number of transfers "
                            "kept is capped at whatever count actually raises your net "
                            "expected score once -4 hits are subtracted, so the overall "
                            "set is never worse than your current squad — full budget use, "
                            "but only the highest score reachable that way.",
                        )
                    num_transfers_to_consider = st.slider(
                        "Number of transfers to consider",
                        0,
                        5,
                        0,
                        disabled=auto_maximize_transfers or maximize_budget_transfers,
                        help="Finds up to this many transfers (same position, affordable, "
                        "respects your estimated free-transfer count, applied together) that "
                        "most improve this gameweek's expected score, then shows the "
                        "resulting Ideal XI. 0 = just your current squad, no transfers.",
                    )

                    if auto_maximize_transfers or maximize_budget_transfers or num_transfers_to_consider > 0:
                        with st.spinner("Scanning every player for the best transfers..."):
                            bank = current_picks["entry_history"].get("bank", 0) / 10.0
                            ranked_all = recommend.recommend_captain(
                                players["id"].tolist(), players, fixtures_data, next_gw
                            )
                            transfer_pool = ranked_all.assign(score=ranked_all["expected_score"])
                            all_suggestions = opt.suggest_transfers(
                                current_ids,
                                transfer_pool,
                                bank=bank,
                                num_transfers=5,
                                free_transfers=free_transfers,
                                budget_weight=1.0 if maximize_budget_transfers else 0.0,
                            )

                            def _apply_transfers(k):
                                ids = list(current_ids)
                                for t in all_suggestions[:k]:
                                    ids = [t["in_id"] if i == t["out_id"] else i for i in ids]
                                return ids

                            def _net_expected_score(k):
                                hypo_ranked = ranked_all[ranked_all["id"].isin(_apply_transfers(k))]
                                hypo_result = opt.best_starting_xi(hypo_ranked, score_col="expected_score")
                                if hypo_result is None:
                                    return None
                                hypo_starters = hypo_ranked[hypo_ranked["id"].isin(hypo_result[0])]
                                hits = sum(4 for t in all_suggestions[:k] if t["is_hit"])
                                return hypo_starters["expected_score"].sum() - hits

                            if auto_maximize_transfers or maximize_budget_transfers:
                                # Both toggles cap the count via net expected score (score
                                # after subtracting -4 hits) — even individually-improving
                                # transfers can net negative once hit costs stack up, and
                                # neither toggle should ever leave you worse off than your
                                # current squad. The slider is disabled while either is on,
                                # so there's no separate manual count to fall back to.
                                best_k, best_net = 0, ideal_starters["expected_score"].sum()
                                for k in range(1, len(all_suggestions) + 1):
                                    net = _net_expected_score(k)
                                    if net is not None and net > best_net:
                                        best_k, best_net = k, net
                                num_to_use = best_k
                            else:
                                num_to_use = num_transfers_to_consider

                        transfer_suggestions = all_suggestions[:num_to_use]

                        if num_to_use == 0:
                            if auto_maximize_transfers or maximize_budget_transfers:
                                st.info(
                                    "No transfer beats your current squad once hit costs are "
                                    "subtracted — 0 transfers is your net-best option, so the "
                                    "Ideal XI above already reflects it."
                                )
                            else:
                                st.info(
                                    "No transfer improves this gameweek's expected score — your "
                                    "current squad is already your best option."
                                )
                        else:
                            st.divider()
                            st.markdown(f"##### Ideal XI with {num_to_use} suggested transfer(s)")
                            if auto_maximize_transfers:
                                st.caption(
                                    f"Maximize potential score picked {num_to_use} transfer(s) — "
                                    "the highest net expected score across every count from 0 to "
                                    "5, hit costs included."
                                )
                            if maximize_budget_transfers:
                                st.caption(
                                    "Maximize budget utilization is on — among transfers that "
                                    "genuinely improve your score, these pick the most "
                                    "expensive affordable option, using expected score to "
                                    "choose between similarly-priced options. Capped to the "
                                    "count that maximizes net expected score, hit costs "
                                    "included."
                                )
                            for i, t in enumerate(transfer_suggestions, start=1):
                                hit_label = " (-4 hit)" if t["is_hit"] else " (free)"
                                st.markdown(
                                    f"**{i}. OUT:** {t['out_name']} ({t['out_team']}, "
                                    f"£{t['out_price']:.1f}m) → **IN:** {t['in_name']} "
                                    f"({t['in_team']}, £{t['in_price']:.1f}m){hit_label}"
                                )
                                st.caption(f"Expected-score gain: +{t['score_gain']:.1f} this gameweek")

                            new_ranked = ranked_all[ranked_all["id"].isin(_apply_transfers(num_to_use))].copy()
                            new_ranked["next_opp"] = new_ranked["team"].map(next_opp_by_team).fillna("—")
                            new_result = (
                                opt.best_starting_xi(new_ranked, score_col="expected_score")
                                if not new_ranked.empty
                                else None
                            )
                            if new_result is None:
                                st.info("Couldn't determine an ideal XI after these transfers.")
                            else:
                                new_starting_ids, new_bench_ids, new_formation = new_result
                                new_starters = new_ranked[new_ranked["id"].isin(new_starting_ids)].sort_values(
                                    "expected_score", ascending=False
                                )
                                new_bench = new_ranked[new_ranked["id"].isin(new_bench_ids)].sort_values(
                                    "expected_score", ascending=False
                                )
                                new_cap, new_vice = opt.pick_captain_vice(new_starters, score_col="expected_score")
                                total_hits = sum(4 for t in transfer_suggestions if t["is_hit"])
                                nm1, nm2, nm3 = st.columns(3, vertical_alignment="center")
                                nm1.metric("Formation with transfers", new_formation)
                                nm2.metric(
                                    "Expected score (XI) with transfers",
                                    f"{new_starters['expected_score'].sum():.1f}",
                                    delta=(
                                        f"{new_starters['expected_score'].sum() - ideal_starters['expected_score'].sum():+.1f}"
                                    ),
                                )
                                nm3.metric(
                                    "Transfer-hit cost",
                                    f"{-total_hits}",
                                    help="Points lost to -4 hits on transfers beyond your free "
                                    "transfers, not yet subtracted from the expected score above.",
                                )
                                new_label = f"**Suggested captain: {new_cap['web_name']}**"
                                if new_vice is not None:
                                    new_label += f" · Vice: {new_vice['web_name']}"
                                st.markdown(new_label)
                                st.dataframe(
                                    new_starters[list(ideal_display_cols)].rename(columns=ideal_display_cols),
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={"Expected": st.column_config.NumberColumn(format="%.1f")},
                                )
                                st.caption("Bench")
                                st.dataframe(
                                    new_bench[list(ideal_display_cols)].rename(columns=ideal_display_cols),
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={"Expected": st.column_config.NumberColumn(format="%.1f")},
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
    else:
        # Viewing a past gameweek: the forward-looking planning tools above
        # (Ideal XI, Transfer Matrix, Chip strategy) are all about what to
        # do next, which doesn't apply to browsing history — show what
        # actually happened that week instead.
        st.markdown(f"#### Transfers made in GW{gw}")
        try:
            all_transfers, _, _, _ = load_entry_transfers(team_id, force_refresh=force_refresh)
        except fpl_api.FPLAPIError as e:
            st.error(f"Could not load transfer history: {e}")
            all_transfers = []
        gw_transfers = [t for t in all_transfers if t["event"] == gw]
        if not gw_transfers:
            st.info(f"No transfers were made in GW{gw}.")
        else:
            id_to_player = players.set_index("id")

            def _describe_transfer_leg(pid, cost):
                if pid in id_to_player.index:
                    row = id_to_player.loc[pid]
                    return f"{row['web_name']} ({row['team_short']}, £{cost / 10:.1f}m)"
                return f"Player {pid} (£{cost / 10:.1f}m)"

            for t in gw_transfers:
                st.markdown(
                    f"**OUT:** {_describe_transfer_leg(t['element_out'], t['element_out_cost'])} "
                    f"→ **IN:** {_describe_transfer_leg(t['element_in'], t['element_in_cost'])}"
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
        "display_name": "Player",
        "team_name": "Team",
        "position": "Pos",
        "price": "£m",
        "score": "Score",
    }
    df = squad_df.copy()
    df["display_name"] = df["web_name"] + df["role"].map({"C": " (C)", "VC": " (VC)"}).fillna("")
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

    def render_optimizer_result(squad_df):
        if squad_df is None:
            st.error("No feasible squad found under these constraints (try a higher budget).")
            return
        starters = squad_df[squad_df["is_starting"]]
        bench = squad_df[~squad_df["is_starting"]]
        m1, m2, m3 = st.columns(3, vertical_alignment="center")
        m1.metric("Formation", opt.formation_label(squad_df))
        m2.metric("Squad cost", f"£{squad_df['price'].sum():.1f}m")
        m3.metric("Predicted score (XI)", f"{starters['score'].sum():.1f}")
        render_squad_table(starters, "Starting XI (C = captain, VC = vice-captain)", next_opponents)
        render_squad_table(bench, "Bench", next_opponents)

    run_col, max_col = st.columns(2)
    run_clicked = run_col.button("Run optimizer", use_container_width=True)
    maximize_clicked = max_col.button(
        "🏆 Maximize score (ignore sliders)", use_container_width=True
    )

    if run_clicked:
        scored = score_with_all_adjustments(players)
        squad_df = opt.optimize_squad(
            scored,
            budget=budget,
            exclude_unavailable=exclude_unavailable,
            formation=formation,
            budget_weight=budget_weight,
        )
        render_optimizer_result(squad_df)

    if maximize_clicked:
        st.caption(
            "Overriding every slider above — full £100.0m budget, no formation lock, pure "
            "score maximization (no budget-utilization bonus, so nothing trades away score "
            "just to spend more), using the recommended weighting (form 0.7 / PPG 0.3, "
            "fixtures 0.5 over the next 5 gameweeks, last season 0.3) since the score itself "
            "still needs some weighting to be defined at all."
        )
        with st.spinner("Fetching last-season stats for all players (first time only)..."):
            prior_stats, _, _, _ = load_prior_season_stats(tuple(players["id"]))
        max_scored = opt.compute_score(players, form_weight=0.7, ppg_weight=0.3)
        max_scored = opt.apply_last_season_adjustment(max_scored, prior_stats, weight=0.3)
        max_scored = opt.apply_fixture_adjustment(
            max_scored, fixtures_data, default_start_gw, 5, fixture_weight=0.5
        )
        squad_df = opt.optimize_squad(
            max_scored, budget=100.0, exclude_unavailable=True, formation=None, budget_weight=0.0
        )
        render_optimizer_result(squad_df)


st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Auto-refresh once per new browser session/page load (not on every widget
# rerun — that would hammer the FPL API on every filter click).
if "did_initial_refresh" not in st.session_state:
    st.session_state.did_initial_refresh = True
    auto_refresh = True
else:
    auto_refresh = False

title_col, refresh_col = st.columns([3, 1], vertical_alignment="center")
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

tab_team_builder, tab_season_overview, tab_player_base, tab_optimizer_draft = st.tabs(
    ["Team Builder", "Season Overview", "PlayerBase", "Optimizer Draft"]
)
with tab_team_builder:
    render_my_team_tab(bootstrap, players, fixtures, force_refresh)
with tab_season_overview:
    render_fixtures_tab(bootstrap, fixtures, fx_error)
with tab_player_base:
    render_players_tab(bootstrap, fixtures, fx_error, manual_refresh)
with tab_optimizer_draft:
    render_optimizer_tab(bootstrap, players, fixtures, force_refresh)
