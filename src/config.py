"""Small local config store (currently just the user's FPL team ID)."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "config.json"


def _read():
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg))


def get_team_id():
    return _read().get("team_id")


def set_team_id(team_id):
    cfg = _read()
    cfg["team_id"] = team_id
    _write(cfg)


def clear_team_id():
    cfg = _read()
    cfg.pop("team_id", None)
    _write(cfg)
