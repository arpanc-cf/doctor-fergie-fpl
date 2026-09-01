"""Chip strategy advisor: personalized suggestions for whether it's worth
playing Bench Boost, Triple Captain, Free Hit, or Wildcard, based on the
manager's actual squad, current form, and upcoming fixtures — not just
generic blank/double-gameweek detection.

Wildcard and Free Hit both let a manager rebuild toward an "optimal" squad
at the same budget; the difference is permanence. This module compares the
manager's current squad against an optimally assembled one (via
optimizer.optimize_squad) at two horizons: just the next gameweek, and
averaged over a longer lookahead. A gap that's only there for the next
gameweek (e.g. a one-off blank) points to Free Hit; a gap that persists
over the longer horizon points to Wildcard instead, since only Wildcard's
change carries forward.
"""

from . import optimizer as opt
from . import recommend

# A gap below this is treated as normal noise in a simple form/PPG proxy,
# not a real signal to burn a chip over.
WILDCARD_GAP_THRESHOLD = 0.15
FREEHIT_GAP_THRESHOLD = 0.15

# Bench averaging at least this fraction of a starter's expected score
# means the bench is strong enough that Bench Boost is worth it.
BENCH_BOOST_RATIO = 0.6

# A standalone bar for a captain's expected score in a single fixture,
# independent of the double-gameweek check, that's high enough on its own
# to justify tripling it.
TRIPLE_CAPTAIN_SCORE_THRESHOLD = 10.0


def available_chips(bootstrap, chips_used, current_gw):
    """{chip_name: True} for each of the 4 chip types whose current
    half-season window (from bootstrap's 'chips' list) covers current_gw
    and hasn't been used yet in that window. FPL grants two of each chip
    (one per half), each announced with its own GW window, so this reads
    the boundary from the API rather than hardcoding gameweek numbers.
    """
    result = {}
    for chip in bootstrap.get("chips", []):
        name, start, stop = chip["name"], chip["start_event"], chip["stop_event"]
        if not (start <= current_gw <= stop):
            continue
        used = any(
            c["name"] == name and start <= c["event"] <= stop for c in chips_used
        )
        result[name] = not used
    return result


def suggest_bench_boost(ideal_starters, ideal_bench, score_col="expected_score"):
    """Bench Boost counts your bench's points too — worth it when your
    bench is projected to score close to what your starters are, not just
    make up the numbers.
    """
    if ideal_bench.empty or ideal_starters.empty:
        return None
    bench_avg = ideal_bench[score_col].mean()
    starter_avg = ideal_starters[score_col].mean()
    recommend_it = starter_avg > 0 and bench_avg >= BENCH_BOOST_RATIO * starter_avg
    return {
        "recommend": recommend_it,
        "bench_total": ideal_bench[score_col].sum(),
        "bench_avg": bench_avg,
        "starter_avg": starter_avg,
    }


def suggest_triple_captain(cap_row, score_col="expected_score"):
    """Triple Captain is best on a double gameweek (the captain scores
    trebled across both fixtures) or an otherwise standout single fixture.
    """
    if cap_row is None:
        return None
    is_double = cap_row.get("fixture_count", 1) >= 2
    captain_score = cap_row[score_col]
    recommend_it = is_double or captain_score >= TRIPLE_CAPTAIN_SCORE_THRESHOLD
    return {
        "recommend": recommend_it,
        "is_double": is_double,
        "captain_score": captain_score,
        "captain_name": cap_row["web_name"],
    }


def _current_vs_optimal(pool_df, current_ids, budget, score_col):
    """Best starting-XI total for the manager's current squad (from
    pool_df, restricted to current_ids) vs. for an optimally assembled
    squad at the same budget (from the full pool_df). Returns
    (current_total, optimal_total); either can be 0 if infeasible.
    """
    current_pool = pool_df[pool_df["id"].isin(current_ids)]
    current_result = opt.best_starting_xi(current_pool, score_col=score_col)
    current_total = (
        current_pool[current_pool["id"].isin(current_result[0])][score_col].sum()
        if current_result
        else 0.0
    )

    optimal_squad = opt.optimize_squad(
        pool_df.assign(score=pool_df[score_col]), budget=budget, exclude_unavailable=True
    )
    optimal_total = (
        optimal_squad[optimal_squad["is_starting"]]["score"].sum()
        if optimal_squad is not None
        else current_total
    )
    return current_total, optimal_total


def suggest_reset_chip(
    players_df,
    current_ids,
    fixtures_data,
    next_gw,
    budget,
    form_weight=0.7,
    ppg_weight=0.3,
    fixture_weight=0.5,
    lookahead_gws=5,
):
    """Compare the manager's current squad against an optimal one at the
    same budget, both for just next_gw (Free Hit territory — a one-week
    reset) and averaged over the next lookahead_gws gameweeks (Wildcard
    territory — a permanent reset). budget should reflect the manager's
    real spending power (current squad value + bank), so the "optimal"
    comparison is achievable, not aspirational.
    """
    all_ids = players_df["id"].tolist()

    ranked_next = recommend.recommend_captain(
        all_ids, players_df, fixtures_data, next_gw, form_weight, ppg_weight
    )
    current_next, optimal_next = _current_vs_optimal(
        ranked_next, current_ids, budget, "expected_score"
    )
    gap_next = max(0.0, (optimal_next - current_next) / current_next) if current_next > 0 else 0.0

    scored_5gw = opt.compute_score(players_df, form_weight=form_weight, ppg_weight=ppg_weight)
    scored_5gw = opt.apply_fixture_adjustment(
        scored_5gw, fixtures_data, next_gw, lookahead_gws, fixture_weight=fixture_weight
    )
    current_5gw, optimal_5gw = _current_vs_optimal(scored_5gw, current_ids, budget, "score")
    gap_5gw = max(0.0, (optimal_5gw - current_5gw) / current_5gw) if current_5gw > 0 else 0.0

    wildcard_worthy = gap_5gw >= WILDCARD_GAP_THRESHOLD
    return {
        "current_next_gw": current_next,
        "optimal_next_gw": optimal_next,
        "gap_next_gw": gap_next,
        "current_lookahead": current_5gw,
        "optimal_lookahead": optimal_5gw,
        "gap_lookahead": gap_5gw,
        "lookahead_gws": lookahead_gws,
        "recommend_wildcard": wildcard_worthy,
        "recommend_freehit": gap_next >= FREEHIT_GAP_THRESHOLD and not wildcard_worthy,
    }
