"""Squad optimizer (PuLP) and greedy transfer suggester.

The optimizer maximizes a simple points-prediction proxy — a blend of
underlying form (process stats: xG, xA, clean-sheet likelihood, saves,
threat/creativity, defensive-contribution likelihood) and season
points-per-game — not a real points forecast. Treat its output as a
starting point for your own judgement, not gospel; "can refine later"
per the project brief.
"""

import math

import pulp

from . import forecast
from .fixtures import team_fixture_multipliers

POSITIONS = ["GKP", "DEF", "MID", "FWD"]
SQUAD_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
STARTING_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
STARTING_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3
# Two players in the same position from the same club are a correlated bet,
# not two independent ones — if that club has a bad defensive or attacking
# week, both go quiet together. Rather than a hard cap on how many a squad
# can hold, the optimizer and transfer suggester apply a soft score penalty
# to such a pair, sized by how far the WEAKER of the two falls short of an
# "elite" bar (that position's own DIVERSIFICATION_ELITE_PERCENTILE score in
# the current player pool). Two genuinely elite teammates cost nothing to
# pair; a strong player alongside a mediocre one from the same club is
# discouraged, since the mediocre pick's value is most likely to evaporate
# exactly when the strong one's does too.
DIVERSIFICATION_ELITE_PERCENTILE = 0.85
DIVERSIFICATION_PENALTY_SCALE = 3.0  # points-equivalent penalty per unit of shortfall below the elite bar
BENCH_WEIGHT = 0.02  # keeps bench selection meaningful without competing with the XI
UNAVAILABLE_STATUSES = {"i", "s", "u"}  # injured, suspended, unavailable/left club
TRANSFER_OUT_AVAILABILITY_BONUS = 2.0  # ranking bonus at full risk; not forecast points
SPEND_BONUS_SCALE = 40  # points-equivalent bonus for spending 100% of budget, at budget_weight=1
# Large enough that, at budget_weight=1, price alone decides between any two
# genuinely score-improving transfer candidates in suggest_transfers.
TRANSFER_BUDGET_DOMINANCE = 1000
STARTING_CHANCE_THRESHOLD = 75  # below this % chance of playing, prefer a safer alternative over raw score

# FPL's own points-per-event values, used to convert underlying process
# stats (xG, xA, clean sheet likelihood, saves) into a points-equivalent
# "underlying form" — see compute_underlying_form.
GOAL_POINTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
SAVE_POINTS_PER_SAVE = 1 / 3
MIN_MINUTES_FOR_UNDERLYING_FORM = 60  # ~1 full match; below this, per-90 rates are wild noise
# A player just past MIN_MINUTES_FOR_UNDERLYING_FORM (e.g. 63 minutes) is still a
# tiny, noisy sample — one lucky big chance can extrapolate to an absurd per-90
# rate. Confidence in the per-90 rate ramps linearly from 0 at the noise floor
# up to full weight once a player has racked up this many minutes (~2 full
# matches) — enough to smooth out a single-cameo fluke without taking half a
# season to trust an established starter's rate.
FULL_CONFIDENCE_MINUTES = 180

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
    cameo goal would otherwise imply an absurd scoring rate). Above that
    floor, confidence in the per-90 rate ramps linearly up to
    FULL_CONFIDENCE_MINUTES — a player a few minutes past the floor still
    has a tiny, noisy sample (one lucky chance can extrapolate to an absurd
    rate), so their estimate is scaled down proportionally rather than
    given the same full weight as an established starter.

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
    confidence = ((minutes - min_minutes) / (FULL_CONFIDENCE_MINUTES - min_minutes)).clip(lower=0, upper=1)
    df["underlying_form"] = underlying * confidence
    return df


def _availability_multiplier(players_df):
    """Expected playing share; a doubtful with no probability is treated as 50%."""
    chance = players_df["chance_of_playing_next_round"]
    status = players_df["status"]
    doubtful_without_chance = status.eq("d") & chance.isna()
    chance = chance.fillna(100).mask(doubtful_without_chance, 50)
    availability = chance / 100.0
    return availability.where(~status.isin(UNAVAILABLE_STATUSES), 0.0)


def _availability_risk(player):
    """0-1 transfer-out urgency from play chance and FPL availability status."""
    status = player.get("status")
    if status in UNAVAILABLE_STATUSES:
        return 1.0
    chance = player.get("chance_of_playing_next_round", 100)
    try:
        chance = float(chance)
    except (TypeError, ValueError):
        chance = 50.0 if status == "d" else 100.0
    if not math.isfinite(chance):
        chance = 50.0 if status == "d" else 100.0
    risk = 1.0 - min(max(chance, 0.0), 100.0) / 100.0
    return max(risk, 0.5) if status == "d" else risk


def compute_score(players_df, form_weight=0.7, ppg_weight=0.3):
    """Add a 'score' column: a blend of underlying form (see
    compute_underlying_form) and points-per-game, scaled down for players
    who are doubtful per their listed chance of playing next round, and
    hard-zeroed for players confirmed injured/suspended/unavailable.

    The hard zero is a separate check from the chance-of-playing discount
    on purpose: that field is usually 0 for such players too, but it isn't
    guaranteed by the API (e.g. a suspension is calendar-certain and
    sometimes left null rather than 0) — checking status directly means a
    confirmed-unavailable player can never sneak into a starting XI
    suggestion just because that one field was missing or stale.
    """
    df = compute_underlying_form(players_df)
    base = form_weight * df["underlying_form"].fillna(0) + ppg_weight * df["points_per_game"].fillna(0)

    availability = _availability_multiplier(df)
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
    availability = _availability_multiplier(df)
    df.loc[has_data, "score"] = (1 - weight) * df.loc[has_data, "score"] + weight * (
        last_ppg90[has_data] * availability[has_data]
    )
    return df


def apply_fixture_adjustment(scored_df, fixtures, start_gw, num_gws, fixture_weight=0.5):
    """Blend each player's score with how favourable their team's next
    num_gws fixtures are — a good run of fixtures boosts the score, a bad
    run or blanks reduce it.

    Uses forecast.py's expected-goals model (fit from this season's actual
    results) when there's enough data: MID/FWD scale with expected goals
    for, GKP/DEF scale with expected clean-sheet probability, both via
    forecast.team_window_multipliers. Falls back to FPL's own 1-5 Fixture
    Difficulty Rating (fixtures.team_fixture_multipliers, applied the same
    way to every position) when there isn't enough finished-match data yet
    to fit the model.

    fixture_weight=0 leaves scores unchanged (the old, fixture-blind
    behavior); fixture_weight=1 applies the full fixture multiplier.
    Values in between interpolate, so a middling weight nudges picks
    toward good fixtures without letting them override a big form/PPG gap.
    """
    if fixture_weight <= 0 or not fixtures:
        return scored_df
    df = scored_df.copy()
    strengths, home_advantage, league_avg_attack = forecast.fit_team_strengths_from_players(fixtures, df)

    if strengths is None:
        raw_multiplier = df["team"].map(team_fixture_multipliers(fixtures, start_gw, num_gws)).fillna(1.0)
    else:
        window = forecast.team_window_multipliers(
            fixtures, start_gw, num_gws, strengths, home_advantage, league_avg_attack
        )
        is_defensive = df["position"].isin(forecast.DEFENSIVE_POSITIONS)
        raw_multiplier = df["team"].map(lambda t: window.get(t, {}).get("attack", 1.0))
        raw_multiplier = raw_multiplier.where(
            ~is_defensive, df["team"].map(lambda t: window.get(t, {}).get("defence", 1.0))
        )

    effective_multiplier = 1 + fixture_weight * (raw_multiplier - 1)
    df["score"] = df["score"] * effective_multiplier
    return df


def _position_elite_thresholds(df):
    """{position: score at the DIVERSIFICATION_ELITE_PERCENTILE within that
    position}, for the diversification penalty below. Computed fresh from
    whatever pool is being considered rather than a fixed constant, since
    the "score" scale itself shifts with the weights it was built from.
    """
    return {
        pos: df.loc[df["position"] == pos, "score"].quantile(DIVERSIFICATION_ELITE_PERCENTILE)
        for pos in df["position"].unique()
    }


def _diversification_penalty(score_a, score_b, elite_threshold):
    """Points-equivalent penalty for rostering/buying two same-club,
    same-position players together — see DIVERSIFICATION_PENALTY_SCALE.
    """
    shortfall = max(elite_threshold - min(score_a, score_b), 0)
    return DIVERSIFICATION_PENALTY_SCALE * shortfall


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

    Also discourages (but doesn't forbid) rostering two same-club,
    same-position players unless both are genuinely elite — see
    DIVERSIFICATION_PENALTY_SCALE.
    """
    df = players_df.reset_index(drop=True)
    if exclude_unavailable:
        df = df[~df["status"].isin(UNAVAILABLE_STATUSES)].reset_index(drop=True)

    formation_counts = parse_formation(formation) if formation else None

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    squad_vars = {i: pulp.LpVariable(f"squad_{i}", cat="Binary") for i in df.index}
    start_vars = {i: pulp.LpVariable(f"start_{i}", cat="Binary") for i in df.index}

    # Same-club, same-position pairs get a soft penalty (see
    # DIVERSIFICATION_PENALTY_SCALE) instead of a hard cap: a "both selected"
    # binary per risky pair, wired to cost points in the objective only when
    # the optimizer actually picks both.
    elite_thresholds = _position_elite_thresholds(df)
    diversification_terms = []
    for (_, pos), group in df.groupby(["team_name", "position"]):
        idxs = group.index.tolist()
        threshold = elite_thresholds.get(pos, 0)
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                penalty = _diversification_penalty(df.loc[i, "score"], df.loc[j, "score"], threshold)
                if penalty <= 0:
                    continue
                pair_var = pulp.LpVariable(f"pair_{i}_{j}", cat="Binary")
                prob += pair_var <= squad_vars[i]
                prob += pair_var <= squad_vars[j]
                prob += pair_var >= squad_vars[i] + squad_vars[j] - 1
                diversification_terms.append(penalty * pair_var)

    spend_bonus_per_unit_price = budget_weight * SPEND_BONUS_SCALE / budget
    prob += (
        pulp.lpSum(
            start_vars[i] * df.loc[i, "score"]
            + BENCH_WEIGHT * squad_vars[i] * df.loc[i, "score"]
            + spend_bonus_per_unit_price * squad_vars[i] * df.loc[i, "price"]
            for i in df.index
        )
        - pulp.lpSum(diversification_terms)
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


def is_starting_eligible(df):
    """True for players safe to name in a starting XI next gameweek: not
    confirmed injured/suspended/unavailable, and not below
    STARTING_CHANCE_THRESHOLD chance of playing (a live doubt, even if not
    yet ruled out).
    """
    chance = _availability_multiplier(df) * 100
    return (chance >= STARTING_CHANCE_THRESHOLD) & (~df["status"].isin(UNAVAILABLE_STATUSES))


def pick_captain_vice(df, score_col="score"):
    """Pick captain/vice from df, preferring players likely to actually
    start (see is_starting_eligible) over a higher-scoring doubt. Falls
    back to score alone if everyone in df is below the threshold, so this
    never fails to return a pick.
    """
    if df.empty:
        return None, None
    ordered = df.assign(_eligible=is_starting_eligible(df)).sort_values(
        ["_eligible", score_col], ascending=[False, False]
    )
    cap = ordered.iloc[0]
    vice = ordered.iloc[1] if len(ordered) > 1 else None
    return cap, vice


def _best_formation_from_pool(squad_df, pool_df, score_col):
    """Try every valid formation using only players in pool_df (a subset of
    squad_df), taking the top-N scorers at each position. Returns the best
    {formation, starting_ids, total} by total score, or None if pool_df
    can't fill any valid formation's position counts.
    """
    best = None
    for formation in VALID_FORMATIONS:
        counts = parse_formation(formation)
        chosen_ids = []
        feasible = True
        for pos, n in counts.items():
            pos_players = pool_df[pool_df["position"] == pos].sort_values(score_col, ascending=False)
            if len(pos_players) < n:
                feasible = False
                break
            chosen_ids.extend(pos_players.head(n)["id"].tolist())
        if not feasible:
            continue
        total = squad_df[squad_df["id"].isin(chosen_ids)][score_col].sum()
        if best is None or total > best["total"]:
            best = {"formation": formation, "starting_ids": chosen_ids, "total": total}
    return best


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

    Players below STARTING_CHANCE_THRESHOLD chance of playing (see
    is_starting_eligible) are excluded from consideration entirely on the
    first pass — including, if needed, by picking a different formation
    that doesn't require them, not just being outranked within their own
    position. They're only allowed back in on a second pass if no valid
    formation can be filled from eligible players alone (e.g. a position
    is so thin on fit players that even the least demanding formation needs
    more than are available).
    """
    eligible_df = squad_df[is_starting_eligible(squad_df)]
    best = _best_formation_from_pool(squad_df, eligible_df, score_col)
    if best is None:
        best = _best_formation_from_pool(squad_df, squad_df, score_col)
    if best is None:
        return None
    starting_ids = set(best["starting_ids"])
    bench_ids = [i for i in squad_df["id"] if i not in starting_ids]
    return starting_ids, bench_ids, best["formation"]


def suggest_transfers(
    current_ids,
    players_df,
    bank,
    num_transfers,
    free_transfers,
    exclude_unavailable=True,
    budget_weight=0.0,
):
    """Greedily suggest up to num_transfers single swaps (same position,
    affordable, club-limit respected) that maximize score gain one at a
    time. Transfers beyond free_transfers are flagged as -4 point hits.

    A squad member is always eligible to be the "out" side of a swap. In
    addition to forecast gain, an availability-risk bonus gives injured,
    suspended, unavailable, and doubtful players more transfer-out priority.
    This ranking bonus is not added to the displayed expected-score gain.
    exclude_unavailable only keeps hard-unavailable players out of the
    incoming "in" pool.

    Every candidate considered must genuinely improve score (gain > 0) —
    this never suggests a downgrade, regardless of budget_weight. A
    candidate that would pair the incoming player with an existing
    same-club, same-position squad-mate has its gain reduced by the same
    diversification penalty used in optimize_squad (see
    DIVERSIFICATION_PENALTY_SCALE) before that check, so a marginal
    upgrade that also concentrates risk in one club needs to clear a
    higher bar.

    budget_weight (0-1) changes which improving swap "best" means among
    those that pass the gain > 0 gate. At 0 (default), the highest-gain
    one wins using expected gain plus an availability-risk bonus. At 1 (full weight, "maximize
    budget utilization"), price dominates the comparison instead, so the
    most expensive still-improving option wins, with score only breaking
    ties among similarly-priced candidates. Paired with a transfer-count
    search that maximizes net score (see the "Maximize potential score"
    caller-side option — worth using here too, since a set of individually
    improving transfers can still net negative once -4 hits are counted),
    this converges on the highest score reachable while leaning toward
    full budget use.

    This is a greedy heuristic, not a global optimum over combinations of
    simultaneous transfers — good enough for "which single swaps help most"
    without a combinatorial search.
    """
    df = players_df.reset_index(drop=True)
    buy_pool = df[~df["status"].isin(UNAVAILABLE_STATUSES)] if exclude_unavailable else df
    elite_thresholds = _position_elite_thresholds(df)

    by_id = df.set_index("id")
    squad_ids = list(current_ids)
    remaining_bank = bank
    # Belt-and-braces against undoing its own earlier moves within the same
    # call — selling a player one step and buying them straight back the
    # next, or buying a player one step and selling them again a step
    # later. The gain > 0 gate makes an exact reversal impossible on its
    # own (its gain is the negative of the original swap's), but this
    # still guards against near-ties across differently-scored pairs. Once
    # sold, a player is never offered as an "in" again; once bought, they're
    # never offered as an "out" again — both within this same call.
    previously_sold_ids = set()
    newly_bought_ids = set()

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
            if out_id not in by_id.index or out_id in newly_bought_ids:
                continue
            out_row = by_id.loc[out_id]
            sell_price = out_row["price"]
            budget_for_buy = remaining_bank + sell_price
            out_club_count_after = club_counts.get(out_row["team_name"], 0) - 1
            # Remaining squad-mates at this position, for the same-club
            # diversification penalty below (out_id itself is leaving).
            same_position_teammates = [
                pid
                for pid in squad_ids
                if pid != out_id and pid in by_id.index and by_id.loc[pid, "position"] == out_row["position"]
            ]
            elite_threshold = elite_thresholds.get(out_row["position"], 0)

            candidates = buy_pool[
                (buy_pool["position"] == out_row["position"])
                & (buy_pool["price"] <= budget_for_buy)
                & (~buy_pool["id"].isin(squad_ids))
                & (~buy_pool["id"].isin(previously_sold_ids))
            ]
            for _, in_row in candidates.iterrows():
                if in_row["team_name"] == out_row["team_name"]:
                    club_after = out_club_count_after + 1
                else:
                    club_after = club_counts.get(in_row["team_name"], 0) + 1
                if club_after > MAX_PER_CLUB:
                    continue
                # Buying in_row alongside an existing same-club, same-position
                # teammate is a correlated bet — see DIVERSIFICATION_PENALTY_SCALE.
                diversification_penalty = sum(
                    _diversification_penalty(in_row["score"], by_id.loc[tid, "score"], elite_threshold)
                    for tid in same_position_teammates
                    if by_id.loc[tid, "team_name"] == in_row["team_name"]
                )
                gain = in_row["score"] - out_row["score"] - diversification_penalty
                if gain <= 0:
                    continue
                availability_bonus = TRANSFER_OUT_AVAILABILITY_BONUS * _availability_risk(out_row)
                price_delta = in_row["price"] - sell_price
                # At budget_weight=1, in_row["price"] * TRANSFER_BUDGET_DOMINANCE
                # dwarfs any realistic score gain, so among the still-improving
                # candidates (gain > 0, enforced above regardless of
                # budget_weight) the priciest one always wins outright, with
                # gain only breaking ties between similarly-priced candidates.
                spend_bonus = budget_weight * in_row["price"] * TRANSFER_BUDGET_DOMINANCE
                adjusted_gain = gain + availability_bonus + spend_bonus
                if best is None or adjusted_gain > best["adjusted_gain"]:
                    best = {
                        "out_id": out_id,
                        "out": out_row,
                        "in": in_row,
                        "gain": gain,
                        "adjusted_gain": adjusted_gain,
                        "cost_delta": price_delta,
                    }

        if best is None:
            break

        previously_sold_ids.add(best["out_id"])
        newly_bought_ids.add(best["in"]["id"])
        squad_ids = [best["in"]["id"] if pid == best["out_id"] else pid for pid in squad_ids]
        remaining_bank -= best["cost_delta"]
        is_hit = n >= free_transfers
        suggestions.append(
            {
                "out_id": best["out_id"],
                "out_name": best["out"]["web_name"],
                "out_team": best["out"]["team_name"],
                "out_price": best["out"]["price"],
                "in_id": best["in"]["id"],
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
