"""Fixture ticker: per-team FDR grid over an upcoming window of gameweeks."""

from collections import defaultdict

import pandas as pd

# Standard FPL FDR color scale (1 = easiest, 5 = hardest).
FDR_STYLE = {
    1: ("#0b6e4f", "white"),
    2: ("#10b981", "black"),
    3: ("#6b7280", "white"),
    4: ("#ef4444", "white"),
    5: ("#7f1d1d", "white"),
}

# Converts an FDR rating into a score multiplier: easier fixtures get a
# boost, harder ones a penalty. A team with no fixture that week (a blank)
# contributes nothing, since it's simply absent from the sum, not multiplied.
FDR_MULTIPLIER = {1: 1.6, 2: 1.3, 3: 1.0, 4: 0.7, 5: 0.4}


def next_gameweek(bootstrap):
    events = bootstrap["events"]
    for e in events:
        if e.get("is_next"):
            return e["id"]
    for e in events:
        if e.get("is_current"):
            return e["id"]
    return 1


def build_fixture_ticker(fixtures, teams_df, start_gw, num_gws):
    """Return (display_df, difficulty_df, avg_fdr), all indexed by full team
    name, columns = the gameweeks in [start_gw, start_gw + num_gws).
    Handles blank gameweeks (no fixture that week) and double gameweeks
    (multiple fixtures that week, joined with " + ").
    """
    team_name = dict(zip(teams_df["id"], teams_df["name"]))
    end_gw = start_gw + num_gws - 1
    gws = list(range(start_gw, end_gw + 1))

    display = defaultdict(lambda: defaultdict(list))
    difficulty = defaultdict(lambda: defaultdict(list))

    for f in fixtures:
        gw = f.get("event")
        if gw is None or not (start_gw <= gw <= end_gw):
            continue
        h, a = f["team_h"], f["team_a"]
        hd, ad = f["team_h_difficulty"], f["team_a_difficulty"]
        display[h][gw].append(f"{team_name.get(a, '?')} (H)")
        difficulty[h][gw].append(hd)
        display[a][gw].append(f"{team_name.get(h, '?')} (A)")
        difficulty[a][gw].append(ad)

    rows_display, rows_difficulty = {}, {}
    for tid, name in team_name.items():
        rows_display[name] = {
            gw: " + ".join(display[tid].get(gw, [])) or "—" for gw in gws
        }
        rows_difficulty[name] = {
            gw: (sum(difficulty[tid][gw]) / len(difficulty[tid][gw]))
            if difficulty[tid].get(gw)
            else None
            for gw in gws
        }

    display_df = pd.DataFrame(rows_display).T[gws]
    difficulty_df = pd.DataFrame(rows_difficulty).T[gws]
    avg_fdr = difficulty_df.mean(axis=1, skipna=True).round(2)
    return display_df, difficulty_df, avg_fdr


def style_ticker(display_df, difficulty_df):
    def colorize(_):
        styles = pd.DataFrame("", index=display_df.index, columns=display_df.columns)
        for col in display_df.columns:
            for idx in display_df.index:
                d = difficulty_df.loc[idx, col]
                if pd.notna(d):
                    bg, fg = FDR_STYLE.get(round(d), ("#333333", "white"))
                    styles.loc[idx, col] = f"background-color: {bg}; color: {fg}"
        return styles

    return display_df.style.apply(colorize, axis=None)


def style_fdr_column(series):
    styles = []
    for d in series:
        if pd.notna(d):
            bg, fg = FDR_STYLE.get(round(d), ("#333333", "white"))
            styles.append(f"background-color: {bg}; color: {fg}")
        else:
            styles.append("")
    return styles


def team_fixture_multipliers(fixtures, start_gw, num_gws):
    """Average per-gameweek FDR multiplier per team over
    [start_gw, start_gw + num_gws) — how favourable a team's run of
    fixtures is. A double gameweek sums both fixtures' multipliers before
    averaging across weeks (rewarding the extra fixture); a blank
    contributes 0 for that week (penalizing a team that doesn't play).
    Teams with no fixtures at all in the window get a neutral 1.0.
    """
    end_gw = start_gw + num_gws - 1
    per_team_per_gw = defaultdict(lambda: defaultdict(float))
    for f in fixtures:
        gw = f.get("event")
        if gw is None or not (start_gw <= gw <= end_gw):
            continue
        h, a = f["team_h"], f["team_a"]
        hd, ad = f["team_h_difficulty"], f["team_a_difficulty"]
        per_team_per_gw[h][gw] += FDR_MULTIPLIER.get(hd, 1.0)
        per_team_per_gw[a][gw] += FDR_MULTIPLIER.get(ad, 1.0)

    multipliers = {}
    for team_id, gw_map in per_team_per_gw.items():
        total = sum(gw_map.values())
        multipliers[team_id] = total / num_gws
    return multipliers


def find_chip_windows(fixtures, teams_df, from_gw=1):
    """Scan the season fixture list for blank gameweeks (some teams have no
    fixture) and double gameweeks (some team has 2+ fixtures) from from_gw
    onward — the two situations where a Free Hit / Bench Boost / Triple
    Captain chip is typically worth timing around.

    Note: fixtures without a scheduled event (postponed, or a rearranged
    cup-congestion clash not yet assigned a gameweek) are skipped, so real
    blanks/doubles created later in the season by rearrangements won't show
    up here until the FPL API assigns them a gameweek.
    """
    team_name = dict(zip(teams_df["id"], teams_df["name"]))
    all_team_ids = set(teams_df["id"])

    counts = defaultdict(lambda: defaultdict(int))  # counts[gw][team_id] = fixture count
    for f in fixtures:
        gw = f.get("event")
        if gw is None or gw < from_gw:
            continue
        counts[gw][f["team_h"]] += 1
        counts[gw][f["team_a"]] += 1

    rows = []
    for gw in sorted(counts):
        gw_counts = counts[gw]
        playing = set(gw_counts)
        blank_teams = sorted(team_name.get(t, "?") for t in (all_team_ids - playing))
        double_teams = sorted(team_name.get(t, "?") for t, c in gw_counts.items() if c >= 2)
        if blank_teams or double_teams:
            rows.append({"event": gw, "blank_teams": blank_teams, "double_teams": double_teams})
    return rows
