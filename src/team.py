"""Derived views over a manager's entry/history/picks data."""

import pandas as pd

MAX_FREE_TRANSFERS = 5
POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


def estimate_free_transfers(history):
    """Best-effort simulation of banked free transfers.

    The FPL API doesn't expose "free transfers remaining" directly, so this
    replicates the standard (2024/25+) ruleset from community knowledge: +1
    free transfer per gameweek from GW2 onward, capped at 5, minus transfers
    made beyond any already-free ones. A wildcard/free-hit gameweek leaves
    the banked count untouched. Treat this as an estimate, not ground truth
    — re-check against the FPL app if it ever looks off after a rule change.
    """
    current = history.get("current", [])
    chips_by_event = {c["event"]: c["name"] for c in history.get("chips", [])}

    ft = 1
    for gw in sorted(current, key=lambda g: g["event"]):
        event = gw["event"]
        if event == 1:
            continue  # opening squad selection, not a transfer gameweek
        if chips_by_event.get(event) in ("wildcard", "freehit"):
            continue
        transfers_made = gw.get("event_transfers", 0)
        hits = gw.get("event_transfers_cost", 0) // 4
        free_used = max(transfers_made - hits, 0)
        ft = min(max(ft - free_used, 0) + 1, MAX_FREE_TRANSFERS)
    return ft


def build_season_history_df(history):
    df = pd.DataFrame(history.get("current", []))
    if df.empty:
        return df
    df["bank_m"] = df["bank"] / 10.0
    df["value_m"] = df["value"] / 10.0
    return df


def build_squad_df(picks_response, players_df, live=None):
    """Merge a picks response with player metadata (and optional live GW
    stats) into a display-ready squad dataframe, ordered GK -> DEF -> MID ->
    FWD, starters before bench.
    """
    picks = pd.DataFrame(picks_response["picks"])
    live_points = {}
    if live is not None:
        live_points = {
            e["id"]: e["stats"]["total_points"] for e in live.get("elements", [])
        }
    picks["gw_points"] = picks["element"].map(live_points).fillna(0).astype(int)
    picks["effective_points"] = picks["gw_points"] * picks["multiplier"]

    # picks["position"] is the pick's *slot order* (1-15); players_df's
    # "position" is the GK/DEF/MID/FWD label — suffixes keep them apart.
    merged = picks.merge(
        players_df[["id", "player", "web_name", "team", "team_short", "team_name", "position", "price"]],
        left_on="element",
        right_on="id",
        how="left",
        suffixes=("_slot", ""),
    )
    merged = merged.rename(columns={"position_slot": "slot"})
    merged["is_starting"] = merged["slot"] <= 11
    merged["role"] = ""
    merged.loc[merged["is_captain"], "role"] = "C"
    merged.loc[merged["is_vice_captain"], "role"] = "VC"
    merged["pos_order"] = merged["position"].map(POSITION_ORDER)

    starters = merged[merged["is_starting"]].sort_values(["pos_order", "slot"])
    bench = merged[~merged["is_starting"]].sort_values("slot")
    return pd.concat([starters, bench], ignore_index=True)
