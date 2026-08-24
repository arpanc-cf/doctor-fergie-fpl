"""Thin client for the (unofficial) FPL public API."""

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
TIMEOUT_SECONDS = 10


class FPLAPIError(Exception):
    """Raised for any network, HTTP, or schema-shaped failure talking to the FPL API."""


def _get(path, params=None):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        raise FPLAPIError(f"Network error calling {url}: {e}") from e

    if resp.status_code != 200:
        raise FPLAPIError(f"FPL API returned HTTP {resp.status_code} for {url}")

    try:
        return resp.json()
    except ValueError as e:
        raise FPLAPIError(f"Invalid JSON from {url}: {e}") from e


def fetch_bootstrap_static():
    return _get("/bootstrap-static/")


def fetch_fixtures(event=None, future=None):
    params = {}
    if event is not None:
        params["event"] = event
    if future is not None:
        params["future"] = int(bool(future))
    return _get("/fixtures/", params=params or None)


def fetch_element_summary(player_id):
    return _get(f"/element-summary/{player_id}/")


def fetch_entry(team_id):
    return _get(f"/entry/{team_id}/")


def fetch_entry_history(team_id):
    return _get(f"/entry/{team_id}/history/")


def fetch_entry_picks(team_id, gw):
    return _get(f"/entry/{team_id}/event/{gw}/picks/")


def fetch_entry_transfers(team_id):
    return _get(f"/entry/{team_id}/transfers/")


def fetch_event_live(gw):
    return _get(f"/event/{gw}/live/")
