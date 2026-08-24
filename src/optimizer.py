"""Squad optimizer (PuLP) and greedy transfer suggester.

The optimizer maximizes a simple points-prediction proxy — a blend of
recent form and season points-per-game — not a real points forecast.
Treat its output as a starting point for your own judgement, not gospel;
"can refine later" per the project brief.
"""

import pulp

from .fixtures import team_fixture_multipliers

POSITIONS = ["GKP", "DEF", "MID", "FWD"]
SQUAD_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
STARTING_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
STARTING_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3
BENCH_WEIGHT = 0.02  # keeps bench selection meaningful without competing with the XI
UNAVAILABLE_STATUSES = {"i", "s", "u"}  # injured, suspended, unavailable/left club
SPEND_BONUS_SCALE = 40  # points-equivalent bonus for spending 100% of budget, at budget_weight=1

# The only DEF-MID-FWD splits of a valid FPL starting XI (1 GK + 10 outfield,
# 3-5 DEF, 2-5 MID, 1-3 FWD) — the same 8 formations selectable in the FPL app.
VALID_FORMATIONS = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"]


def parse_formation(formation):
    d, m, f = (int(x) for x in formation.split("-"))
    return {"GKP": 1, "DEF": d, "MID": m, "FWD": f}


def compute_score(players_df, form_weight=0.7, ppg_weight=0.3):
    """Add a 'score' column: a blend of recent form and points-per-game,
    scaled down for players who are doubtful/injured per their listed
    chance of playing next round.
    """
    df = players_df.copy()
    base = form_weight * df["form"].fillna(0) + ppg_weight * df["points_per_game"].fillna(0)

    availability = df["chance_of_playing_next_round"].fillna(100) / 100.0
    df["score"] = base * availability
    return df


def apply_last_season_adjustment(scored_df, prior_stats, weight=0.3):
    """Blend each player's score with their points-per-90 from their most
    recent completed season (see history.fetch_prior_season_stats) — a
    stabilizing prior against thin in-season form/PPG samples, especially
    early on. Players with no qualifying prior season (promoted-team
    debutants, new-to-the-league signings, fringe players) are left
    unchanged — judged on current-season data only, since there's nothing
    to blend in for them.

    weight=0 leaves scores unchanged; weight=1 replaces the score with the
    prior-season rate entirely (only for players who have one).

    Currently injured/suspended players must stay near-zero regardless of
    how good they were last season, so the prior-season component is
    scaled by the same current chance-of-playing used in compute_score —
    otherwise an injured star would get an undeserved score boost from
    last year's form alone.
    """
    if weight <= 0 or not prior_stats:
        return scored_df
    df = scored_df.copy()
    last_ppg90 = df["id"].astype(str).map(
        lambda i: prior_stats.get(i, {}).get("points_per_90")
    )
    has_data = last_ppg90.notna()
    availability = df["chance_of_playing_next_round"].fillna(100) / 100.0
    df.loc[has_data, "score"] = (1 - weight) * df.loc[has_data, "score"] + weight * (
        last_ppg90[has_data] * availability[has_data]
    )
    return df


def apply_fixture_adjustment(scored_df, fixtures, start_gw, num_gws, fixture_weight=0.5):
    """Blend each player's score with how favourable their team's next
    num_gws fixtures are (see fixtures.team_fixture_multipliers) — a good
    run of fixtures boosts the score, a bad run or blanks reduce it.

    fixture_weight=0 leaves scores unchanged (the old, fixture-blind
    behavior); fixture_weight=1 applies the full fixture multiplier.
    Values in between interpolate, so a middling weight nudges picks
    toward good fixtures without letting them override a big form/PPG gap.
    """
    if fixture_weight <= 0 or not fixtures:
        return scored_df
    df = scored_df.copy()
    multipliers = team_fixture_multipliers(fixtures, start_gw, num_gws)
    raw_multiplier = df["team"].map(multipliers).fillna(1.0)
    effective_multiplier = 1 + fixture_weight * (raw_multiplier - 1)
    df["score"] = df["score"] * effective_multiplier
    return df


def optimize_squad(players_df, budget=100.0, exclude_unavailable=True, formation=None, budget_weight=0.0):
    """Pick the best 15-man squad + starting XI under budget/quota/club-limit
    constraints. Returns a squad dataframe (15 rows, with is_starting and
    role columns) or None if no feasible squad exists (e.g. budget too low).

    formation: one of VALID_FORMATIONS (e.g. "4-4-2") to force that exact
    DEF-MID-FWD split for the starting XI, or None to let the optimizer pick
    whichever formation scores highest.

    budget_weight: 0-1, how much to reward spending closer to the full
    budget. At 0 (default) only the score proxy matters, so the optimizer
    may leave money unspent if it doesn't buy extra score. At 1, spending
    the full budget is worth up to SPEND_BONUS_SCALE points-equivalent,
    which can outweigh small score differences and pull picks toward
    pricier players even when they don't score much higher.
    """
    df = players_df.reset_index(drop=True)
    if exclude_unavailable:
        df = df[~df["status"].isin(UNAVAILABLE_STATUSES)].reset_index(drop=True)

    formation_counts = parse_formation(formation) if formation else None

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    squad_vars = {i: pulp.LpVariable(f"squad_{i}", cat="Binary") for i in df.index}
    start_vars = {i: pulp.LpVariable(f"start_{i}", cat="Binary") for i in df.index}

    spend_bonus_per_unit_price = budget_weight * SPEND_BONUS_SCALE / budget
    prob += pulp.lpSum(
        start_vars[i] * df.loc[i, "score"]
        + BENCH_WEIGHT * squad_vars[i] * df.loc[i, "score"]
        + spend_bonus_per_unit_price * squad_vars[i] * df.loc[i, "price"]
        for i in df.index
    )

    prob += pulp.lpSum(squad_vars[i] for i in df.index) == 15
    prob += pulp.lpSum(squad_vars[i] * df.loc[i, "price"] for i in df.index) <= budget
    prob += pulp.lpSum(start_vars[i] for i in df.index) == 11

    for i in df.index:
        prob += start_vars[i] <= squad_vars[i]

    for pos, n in SQUAD_QUOTA.items():
        idxs = [i for i in df.index if df.loc[i, "position"] == pos]
        prob += pulp.lpSum(squad_vars[i] for i in idxs) == n

    for pos in POSITIONS:
        idxs = [i for i in df.index if df.loc[i, "position"] == pos]
        if formation_counts:
            prob += pulp.lpSum(start_vars[i] for i in idxs) == formation_counts[pos]
        else:
            prob += pulp.lpSum(start_vars[i] for i in idxs) >= STARTING_MIN[pos]
            prob += pulp.lpSum(start_vars[i] for i in idxs) <= STARTING_MAX[pos]

    for club in df["team_name"].unique():
        idxs = [i for i in df.index if df.loc[i, "team_name"] == club]
        prob += pulp.lpSum(squad_vars[i] for i in idxs) <= MAX_PER_CLUB

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        return None

    df["is_starting"] = [pulp.value(start_vars[i]) > 0.5 for i in df.index]
    in_squad = [pulp.value(squad_vars[i]) > 0.5 for i in df.index]
    squad_df = df[in_squad].copy()

    squad_df["role"] = ""
    starters = squad_df[squad_df["is_starting"]].sort_values("score", ascending=False)
    if len(starters) >= 1:
        squad_df.loc[starters.index[0], "role"] = "C"
    if len(starters) >= 2:
        squad_df.loc[starters.index[1], "role"] = "VC"

    pos_order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    squad_df["pos_order"] = squad_df["position"].map(pos_order)
    squad_df = squad_df.sort_values(
        ["is_starting", "pos_order", "score"], ascending=[False, True, False]
    ).reset_index(drop=True)
    return squad_df


def formation_label(squad_df):
    starters = squad_df[squad_df["is_starting"]]
    counts = starters["position"].value_counts()
    return f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"


def suggest_transfers(current_ids, players_df, bank, num_transfers, free_transfers, exclude_unavailable=True):
    """Greedily suggest up to num_transfers single swaps (same position,
    affordable, club-limit respected) that maximize score gain one at a
    time. Transfers beyond free_transfers are flagged as -4 point hits.

    This is a greedy heuristic, not a global optimum over combinations of
    simultaneous transfers — good enough for "which single swaps help most"
    without a combinatorial search.
    """
    df = players_df.reset_index(drop=True)
    if exclude_unavailable:
        df = df[~df["status"].isin(UNAVAILABLE_STATUSES)].reset_index(drop=True)

    by_id = df.set_index("id")
    squad_ids = list(current_ids)
    remaining_bank = bank

    suggestions = []
    for n in range(num_transfers):
        best = None
        club_counts = {}
        for pid in squad_ids:
            if pid in by_id.index:
                club_counts[by_id.loc[pid, "team_name"]] = club_counts.get(
                    by_id.loc[pid, "team_name"], 0
                ) + 1

        for out_id in squad_ids:
            if out_id not in by_id.index:
                continue
            out_row = by_id.loc[out_id]
            sell_price = out_row["price"]
            budget_for_buy = remaining_bank + sell_price
            out_club_count_after = club_counts.get(out_row["team_name"], 0) - 1

            candidates = df[
                (df["position"] == out_row["position"])
                & (df["price"] <= budget_for_buy)
                & (~df["id"].isin(squad_ids))
            ]
            for _, in_row in candidates.iterrows():
                if in_row["team_name"] == out_row["team_name"]:
                    club_after = out_club_count_after + 1
                else:
                    club_after = club_counts.get(in_row["team_name"], 0) + 1
                if club_after > MAX_PER_CLUB:
                    continue
                gain = in_row["score"] - out_row["score"]
                if best is None or gain > best["gain"]:
                    best = {
                        "out_id": out_id,
                        "out": out_row,
                        "in": in_row,
                        "gain": gain,
                        "cost_delta": in_row["price"] - sell_price,
                    }

        if best is None or best["gain"] <= 0:
            break

        squad_ids = [best["in"]["id"] if pid == best["out_id"] else pid for pid in squad_ids]
        remaining_bank -= best["cost_delta"]
        is_hit = n >= free_transfers
        suggestions.append(
            {
                "out_name": best["out"]["web_name"],
                "out_team": best["out"]["team_short"],
                "out_price": best["out"]["price"],
                "in_name": best["in"]["web_name"],
                "in_team": best["in"]["team_short"],
                "in_price": best["in"]["price"],
                "score_gain": best["gain"],
                "cost_delta": best["cost_delta"],
                "is_hit": is_hit,
                "net_gain": best["gain"] - (4 if is_hit else 0),
            }
        )

    return suggestions
