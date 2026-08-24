"""Captain/vice-captain recommendation for a specific gameweek.

Combines the optimizer's form/points-per-game score proxy with that
gameweek's fixture difficulty for each player's team, so a player with an
easy fixture (or a double gameweek) ranks above one with a tough game or a
blank — which the season-average score alone wouldn't capture.
"""

from . import optimizer as opt
from .fixtures import FDR_MULTIPLIER


def _team_fixture_difficulties(fixtures, gw):
    """{team_id: [fdr, ...]} for the given gameweek (list length 2+ = DGW)."""
    result = {}
    for f in fixtures:
        if f.get("event") != gw:
            continue
        result.setdefault(f["team_h"], []).append(f["team_h_difficulty"])
        result.setdefault(f["team_a"], []).append(f["team_a_difficulty"])
    return result


def recommend_captain(current_ids, players_df, fixtures, gw, form_weight=0.7, ppg_weight=0.3):
    """Rank the given player ids (typically a squad's starting XI) by
    expected score for gameweek `gw`, highest first. Returns a dataframe
    with 'expected_score' and 'fixture_count' (0 = blank gameweek).
    """
    scored = opt.compute_score(players_df, form_weight=form_weight, ppg_weight=ppg_weight)
    scored = scored[scored["id"].isin(current_ids)].copy()

    fdr_map = _team_fixture_difficulties(fixtures, gw)

    def expected_score(row):
        fdrs = fdr_map.get(row["team"], [])
        return sum(row["score"] * FDR_MULTIPLIER.get(fdr, 1.0) for fdr in fdrs)

    scored["fixture_count"] = scored["team"].map(lambda t: len(fdr_map.get(t, [])))
    scored["expected_score"] = scored.apply(expected_score, axis=1)
    return scored.sort_values("expected_score", ascending=False).reset_index(drop=True)
