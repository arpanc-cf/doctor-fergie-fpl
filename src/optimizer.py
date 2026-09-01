"""Squad optimizer (PuLP) and greedy transfer suggester.

The optimizer maximizes a simple points-prediction proxy — a blend of
underlying form (process stats: xG, xA, clean-sheet likelihood, saves,
threat/creativity, defensive-contribution likelihood) and season
points-per-game — not a real points forecast. Treat its output as a
starting point for your own judgement, not gospel; "can refine later"
per the project brief.
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

# FPL's own points-per-event values, used to convert underlying process
# stats (xG, xA, clean sheet likelihood, saves) into a points-equivalent
# "underlying form" — see compute_underlying_form.
GOAL_POINTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
SAVE_POINTS_PER_SAVE = 1 / 3
MIN_MINUTES_FOR_UNDERLYING_FORM = 60  # ~1 full match; below this, per-90 rates are wild noise

# Threat/creativity are FPL's own ICT-index components (shot-based attacking
# threat, chance-creation) — the closest public proxy for shots/shots-on-target
# and chances-created, since the FPL API doesn't expose those directly. Scaled
# down from their raw index units so a very high performer adds a few
# points-equivalent, not enough to swamp the goal/assist-based components.
ICT_COMPONENT_SCALE = 0.03

# FPL's 2025/26 "defensive contribution" bonus: +2 pts in a match once combined
# defensive actions (tackles + interceptions + clearances/blocks, plus
# recoveries for MID/FWD) clears a threshold. Goalkeepers aren't eligible.
# This is the closest available proxy for tackles/duels-won/clearances.
DEFENSIVE_CONTRIBUTION_POINTS = 2
DEFENSIVE_CONTRIBUTION_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}

# The only DEF-MID-FWD splits of a valid FPL starting XI (1 GK + 10 outfield,
# 3-5 DEF, 2-5 MID, 1-3 FWD) — the same 8 formations selectable in the FPL app.
VALID_FORMATIONS = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"]


def parse_formation(formation):
    d, m, f = (int(x) for x in formation.split("-"))
    return {"GKP": 1, "DEF": d, "MID": m, "FWD": f}


def compute_underlying_form(players_df, min_minutes=MIN_MINUTES_FOR_UNDERLYING_FORM):
    """Add an 'underlying_form' column: a points-per-90 estimate built from
    process stats (expected goals, expected assists, clean-sheet
    likelihood, saves) rather than points already scored — deliberately
    independent of total_points/points_per_game, since early in a season
    FPL's own 'form' field is just a recent-points average that collapses
    to the same number as points-per-game and total points (there's only
    been one or two gameweeks to average over).

    Each stat is weighted by FPL's own points-per-event values, which
    differ by position (e.g. a defender's clean sheet is worth 4pts, a
    forward's is worth 0) — so a defender racking up clean sheets and a
    forward racking up expected goals both surface, appropriately.

    Clean-sheet likelihood is approximated as 1 - expected_goals_conceded
    per 90 (clipped to [0, 1]) — a rough but explainable proxy, not a real
    probability model. Players under min_minutes get 0: with so few
    minutes, a per-90 rate is more noise than signal (a single stoppage-time
    cameo goal would otherwise imply an absurd scoring rate).

    Also folds in, for all positions, a small threat/creativity component
    (FPL's own ICT-index proxies for shot volume and chance creation — the
    API doesn't expose raw shots/shots-on-target/chances-created), and for
    outfield positions an estimated defensive-contribution points
    likelihood (built from tackles + interceptions + clearances/blocks,
    plus recoveries for MID/FWD — the closest available proxy for
    tackles-won/duels-won/clearances, since the FPL API doesn't expose
    those individually). Goalkeepers aren't eligible for defensive
    contribution points under FPL's rules, so they get 0 for that piece.
    """
    df = players_df.copy()
    minutes = df["minutes"].fillna(0)
    per90 = 90.0 / minutes.clip(lower=1)

    xg90 = df["expected_goals"].fillna(0) * per90
    xa90 = df["expected_assists"].fillna(0) * per90
    xgc90 = df["expected_goals_conceded"].fillna(0) * per90
    saves90 = df["saves"].fillna(0) * per90
    threat90 = df["threat"].fillna(0) * per90
    creativity90 = df["creativity"].fillna(0) * per90
    dc90 = df["defensive_contribution"].fillna(0) * per90

    goal_pts = df["position"].map(GOAL_POINTS).fillna(4)
    cs_pts = df["position"].map(CLEAN_SHEET_POINTS).fillna(0)
    cs_likelihood = (1 - xgc90).clip(lower=0, upper=1)

    dc_threshold = df["position"].map(DEFENSIVE_CONTRIBUTION_THRESHOLD)
    dc_likelihood = (dc90 / dc_threshold).clip(lower=0, upper=1).fillna(0)
    dc_contribution = dc_likelihood * DEFENSIVE_CONTRIBUTION_POINTS

    underlying = (
        xg90 * goal_pts
        + xa90 * ASSIST_POINTS
        + cs_likelihood * cs_pts
        + saves90 * SAVE_POINTS_PER_SAVE
        + (threat90 + creativity90) * ICT_COMPONENT_SCALE
        + dc_contribution
    )
    df["underlying_form"] = underlying.where(minutes >= min_minutes, 0.0)
    return df


def compute_score(players_df, form_weight=0.7, ppg_weight=0.3):
    """Add a 'score' column: a blend of underlying form (see
    compute_underlying_form) and points-per-game, scaled down for players
    who are doubtful/injured per their listed chance of playing next round.
    """
    df = compute_underlying_form(players_df)
    base = form_weight * df["underlying_form"].fillna(0) + ppg_weight * df["points_per_game"].fillna(0)

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


def best_starting_xi(squad_df, score_col="score"):
    """Given a fixed 15-player squad (e.g. a manager's actual squad — no
    budget/transfers involved), pick the best-scoring valid starting XI.

    Unlike optimize_squad, this doesn't need a MILP: with the 15 players
    already fixed, a formation's position counts are the only constraint,
    and nothing else links positions together — so for a given formation,
    taking the top-N scorers at each position is provably optimal. This
    just compares that result across all 8 valid formations and keeps the
    best, which is therefore the global optimum for this squad.

    Returns (starting_ids, bench_ids, formation_label), or None if the
    squad doesn't have enough players at some position for any valid
    formation (shouldn't happen for a real 2/5/5/3 FPL squad).
    """
    best = None
    for formation in VALID_FORMATIONS:
        counts = parse_formation(formation)
        chosen_ids = []
        feasible = True
        for pos, n in counts.items():
            pos_players = squad_df[squad_df["position"] == pos].sort_values(score_col, ascending=False)
            if len(pos_players) < n:
                feasible = False
                break
            chosen_ids.extend(pos_players.head(n)["id"].tolist())
        if not feasible:
            continue
        total = squad_df[squad_df["id"].isin(chosen_ids)][score_col].sum()
        if best is None or total > best["total"]:
            best = {"formation": formation, "starting_ids": chosen_ids, "total": total}

    if best is None:
        return None
    starting_ids = set(best["starting_ids"])
    bench_ids = [i for i in squad_df["id"] if i not in starting_ids]
    return starting_ids, bench_ids, best["formation"]


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
                "out_team": best["out"]["team_name"],
                "out_price": best["out"]["price"],
                "in_name": best["in"]["web_name"],
                "in_team": best["in"]["team_name"],
                "in_price": best["in"]["price"],
                "score_gain": best["gain"],
                "cost_delta": best["cost_delta"],
                "is_hit": is_hit,
                "net_gain": best["gain"] - (4 if is_hit else 0),
            }
        )

    return suggestions
