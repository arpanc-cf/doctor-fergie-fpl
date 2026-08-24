"""Prior-season performance per player, from the FPL API's per-player
element-summary endpoint. There's no bulk endpoint for this — it's one
HTTP call per player — so this fetches concurrently (~15s for the full
~600-player set) and the result is meant to be cached long-term, since a
completed season's stats never change.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import fpl_api

MIN_MINUTES = 450  # ~5 full matches; below this a points-per-90 rate is too noisy to trust
MAX_WORKERS = 20


def _fetch_one(player_id):
    try:
        summary = fpl_api.fetch_element_summary(player_id)
    except fpl_api.FPLAPIError:
        return player_id, None

    history_past = summary.get("history_past") or []
    if not history_past:
        return player_id, None

    last_season = history_past[-1]
    minutes = last_season.get("minutes", 0)
    if minutes < MIN_MINUTES:
        return player_id, None

    return player_id, {
        "season_name": last_season["season_name"],
        "total_points": last_season["total_points"],
        "minutes": minutes,
        "points_per_90": last_season["total_points"] / (minutes / 90.0),
    }


def fetch_prior_season_stats(player_ids):
    """Return {str(player_id): {season_name, total_points, minutes,
    points_per_90}} for players with a completed prior season and enough
    minutes in it to trust the rate. Players absent from the result are
    promoted-team debutants, new-to-the-league signings, or fringe players
    with too little prior data — callers should treat them as "no prior
    season to draw on" rather than penalizing them.

    Keyed by string player id (not int) because this is cached as JSON,
    which always round-trips object keys as strings — using str() from the
    start avoids an int/str mismatch after the first cache read.
    """
    stats = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_fetch_one, pid) for pid in player_ids]
        for future in as_completed(futures):
            player_id, data = future.result()
            if data is not None:
                stats[str(player_id)] = data
    return stats
