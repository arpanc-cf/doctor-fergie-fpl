"""Captain/vice-captain recommendation for a specific gameweek.

Combines the optimizer's form/points-per-game/last-season score proxy with
that gameweek's fixture-specific outlook, so a player with an easy fixture
(or a double gameweek) ranks above one with a tough game or a blank —
which the season-average score alone wouldn't capture.

The fixture outlook itself comes from forecast.py's expected-goals model,
fit from this season's actual results, whenever there's enough data:
attacking positions (MID/FWD) scale with the team's expected goals for
this fixture, GKP/DEF scale with the fixture's expected clean-sheet
probability — both relative to that team's own season average. Falls back
to FPL's own 1-5 Fixture Difficulty Rating (the old proxy) when there
isn't enough finished-match data yet to fit the model (very early
preseason).
"""

from . import forecast, optimizer as opt
from .fixtures import FDR_MULTIPLIER


def _team_fixtures_for_gw(fixtures, gw):
    """{team_id: [(opponent_id, is_home, fdr), ...]} for the given
    gameweek (list length 2+ = a double gameweek). fdr rides along for the
    FDR-proxy fallback path.
    """
    result = {}
    for f in fixtures:
        if f.get("event") != gw:
            continue
        result.setdefault(f["team_h"], []).append((f["team_a"], True, f["team_h_difficulty"]))
        result.setdefault(f["team_a"], []).append((f["team_h"], False, f["team_a_difficulty"]))
    return result


def recommend_captain(
    current_ids,
    players_df,
    fixtures,
    gw,
    form_weight=0.7,
    ppg_weight=0.3,
    prior_stats=None,
    last_season_weight=0.3,
):
    """Rank the given player ids (typically a squad's starting XI) by
    expected score for gameweek `gw`, highest first. Returns a dataframe
    with 'expected_score' and 'fixture_count' (0 = blank gameweek).

    prior_stats/last_season_weight (see optimizer.apply_last_season_adjustment)
    blend in each player's last-completed-season points-per-90 as a
    stabilizing prior — the same default methodology Optimizer Draft's
    "Maximize score" uses, so Team Builder's captain, transfer, and chip
    suggestions are scored consistently with it rather than on a form/PPG-
    only proxy. Pass prior_stats=None (the default) to skip this, e.g.
    before it's been fetched yet.
    """
    scored = opt.compute_score(players_df, form_weight=form_weight, ppg_weight=ppg_weight)
    if prior_stats:
        scored = opt.apply_last_season_adjustment(scored, prior_stats, weight=last_season_weight)
    scored = scored[scored["id"].isin(current_ids)].copy()

    strengths, home_advantage, league_avg_attack = forecast.fit_team_strengths_from_players(fixtures, players_df)

    fixture_map = _team_fixtures_for_gw(fixtures, gw)

    def fixture_multiplier(team_id, opponent_id, is_home, position, fdr):
        if strengths is None:
            return FDR_MULTIPLIER.get(fdr, 1.0)
        exp_for, exp_against = forecast.expected_goals_for_team(
            strengths, home_advantage, team_id, opponent_id, is_home
        )
        if position in forecast.DEFENSIVE_POSITIONS:
            return forecast.defensive_multiplier(strengths, league_avg_attack, team_id, exp_against)
        return forecast.attacking_multiplier(strengths, team_id, exp_for)

    def expected_score(row):
        return sum(
            row["score"] * fixture_multiplier(row["team"], opponent_id, is_home, row["position"], fdr)
            for opponent_id, is_home, fdr in fixture_map.get(row["team"], [])
        )

    scored["fixture_count"] = scored["team"].map(lambda t: len(fixture_map.get(t, [])))
    scored["expected_score"] = scored.apply(expected_score, axis=1)
    return scored.sort_values("expected_score", ascending=False).reset_index(drop=True)
