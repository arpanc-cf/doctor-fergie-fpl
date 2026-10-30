"""Walk-forward calibration for Doctor Fergie's player score weights.

Downloads public FPL gameweek files, reconstructs features as they stood before
each 2025/26 gameweek, tunes weights on GW1-25, and reports untouched holdout
results on GW26-38. The previous season contributes only its points-per-90
prior. The FPL xP column is deliberately not used because archived snapshots
may contain a post-match value.

Run from the repository root:
    python scripts/backtest_score_weights.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import json
import re
import time
import unicodedata

import numpy as np
import pandas as pd
import requests

from src import optimizer


DATA_BASE = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/"
    "master/data/{season}/gws/gw{gameweek}.csv"
)
PRIOR_SEASON = "2024-25"
CURRENT_SEASON = "2025-26"
TRAIN_GWS = range(1, 26)
HOLDOUT_GWS = range(26, 39)
MIN_PRIOR_MINUTES = 450
WORKERS = 8

SUM_COLUMNS = [
    "minutes",
    "total_points",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "saves",
    "threat",
    "creativity",
    "defensive_contribution",
]
FEATURE_COLUMNS = [
    "minutes",
    "total_points",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "saves",
    "threat",
    "creativity",
    "defensive_contribution",
    "appearances",
]


def normalize_name(value: object) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", value.lower())).strip()


def fetch_gameweek(args: tuple[str, int]) -> tuple[int, pd.DataFrame]:
    season, gameweek = args
    url = DATA_BASE.format(season=season, gameweek=gameweek)
    last_error = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return gameweek, pd.read_csv(StringIO(response.text))
        except requests.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not download {season} GW{gameweek}: {last_error}")


def load_season(season: str) -> dict[int, pd.DataFrame]:
    """Download and aggregate the fixture rows into one player row per GW."""
    loaded: dict[int, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [
            pool.submit(fetch_gameweek, (season, gameweek))
            for gameweek in range(1, 39)
        ]
        for future in as_completed(futures):
            gameweek, raw = future.result()
            raw = raw.copy()
            if "defensive_contribution" not in raw:
                raw["defensive_contribution"] = 0.0
            for column in SUM_COLUMNS:
                if column not in raw:
                    raw[column] = 0.0
                raw[column] = pd.to_numeric(raw[column], errors="coerce").fillna(0.0)
            raw["position"] = raw["position"].replace({"GK": "GKP"})
            grouped = raw.groupby("element", as_index=False).agg(
                name=("name", "first"),
                position=("position", "first"),
                **{column: (column, "sum") for column in SUM_COLUMNS},
            )
            grouped["appearances"] = grouped["minutes"].gt(0).astype(float)
            loaded[gameweek] = grouped
    return loaded


def prior_season_rates(
    season_rows: dict[int, pd.DataFrame],
) -> dict[str, float]:
    all_rows = pd.concat(season_rows.values(), ignore_index=True)
    summary = all_rows.groupby("name", as_index=False).agg(
        minutes=("minutes", "sum"),
        total_points=("total_points", "sum"),
    )
    summary = summary[summary["minutes"] >= MIN_PRIOR_MINUTES]
    return {
        normalize_name(row.name): 90.0 * row.total_points / row.minutes
        for row in summary.itertuples()
    }


def build_walk_forward_examples(
    current_rows: dict[int, pd.DataFrame],
    prior_rates: dict[str, float],
) -> pd.DataFrame:
    examples: list[pd.DataFrame] = []
    cumulative: pd.DataFrame | None = None

    for gameweek in range(1, 39):
        target = current_rows[gameweek]
        if cumulative is None:
            before = target[["element", "name", "position"]].copy()
            for column in FEATURE_COLUMNS:
                before[column] = 0.0
        else:
            before = target[["element", "name", "position"]].merge(
                cumulative[["element", *FEATURE_COLUMNS]],
                on="element",
                how="left",
            )
            before[FEATURE_COLUMNS] = before[FEATURE_COLUMNS].fillna(0.0)

        before["id"] = before["element"].astype(str)
        before["web_name"] = before["name"]
        before["chance_of_playing_next_round"] = 100.0
        before["status"] = "a"
        before["points_per_game"] = (
            before["total_points"] / before["appearances"].clip(lower=1)
        )
        before["prior_points_per_90"] = before["name"].map(
            lambda name: prior_rates.get(normalize_name(name), np.nan)
        )

        # Use the app's current process-stat formula so the backtest tracks
        # future changes to those calculations.
        featured = optimizer.compute_underlying_form(before)
        target_points = target.set_index("element")["total_points"]
        target_minutes = target.set_index("element")["minutes"]
        featured["actual_points"] = featured["element"].map(target_points)
        featured["target_minutes"] = featured["element"].map(target_minutes)
        featured["current_minutes"] = featured["minutes"].fillna(0.0)
        featured["gameweek"] = gameweek
        played = featured[featured["target_minutes"] > 0].copy()
        examples.append(
            played[
                [
                    "underlying_form",
                    "points_per_game",
                    "prior_points_per_90",
                    "current_minutes",
                    "actual_points",
                    "position",
                    "gameweek",
                ]
            ]
        )

        if cumulative is None:
            cumulative = target[["element", *FEATURE_COLUMNS]].copy()
        else:
            old = cumulative.set_index("element")[FEATURE_COLUMNS]
            new = target.set_index("element")[FEATURE_COLUMNS]
            totals = old.add(new, fill_value=0.0).reset_index()
            cumulative = target[["element"]].merge(totals, on="element", how="left")

    return pd.concat(examples, ignore_index=True)


def predict(
    rows: pd.DataFrame,
    form_weight: float,
    prior_start_weight: float,
    prior_half_life_minutes: float,
) -> pd.Series:
    base = (
        form_weight * rows["underlying_form"]
        + (1.0 - form_weight) * rows["points_per_game"]
    )
    prior = rows["prior_points_per_90"]
    prior_weight = prior_start_weight * np.power(
        0.5, rows["current_minutes"] / prior_half_life_minutes
    )
    return base.where(prior.isna(), (1.0 - prior_weight) * base + prior_weight * prior)


def evaluate(
    rows: pd.DataFrame,
    form_weight: float,
    prior_start_weight: float,
    prior_half_life_minutes: float,
) -> dict[str, float | int]:
    prediction = predict(rows, form_weight, prior_start_weight, prior_half_life_minutes)
    error = prediction - rows["actual_points"]
    return {
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "spearman": float(prediction.corr(rows["actual_points"], method="spearman")),
        "n": int(len(rows)),
    }


def main() -> None:
    print(f"Loading {PRIOR_SEASON} prior-season data and {CURRENT_SEASON} gameweeks...")
    prior_rows = load_season(PRIOR_SEASON)
    current_rows = load_season(CURRENT_SEASON)
    examples = build_walk_forward_examples(
        current_rows, prior_season_rates(prior_rows)
    )
    training = examples[examples["gameweek"].isin(TRAIN_GWS)]
    holdout = examples[examples["gameweek"].isin(HOLDOUT_GWS)]

    baseline = {
        "form": 0.70,
        "prior_start": 0.30,
        "prior_half_life_minutes": 1e12,
    }
    baseline_train = evaluate(training, **{
        "form_weight": baseline["form"],
        "prior_start_weight": baseline["prior_start"],
        "prior_half_life_minutes": baseline["prior_half_life_minutes"],
    })
    baseline_holdout = evaluate(holdout, **{
        "form_weight": baseline["form"],
        "prior_start_weight": baseline["prior_start"],
        "prior_half_life_minutes": baseline["prior_half_life_minutes"],
    })

    candidates = []
    half_lives = (180, 270, 360, 540, 720, 900, 1260, 1800)
    for form_weight in np.arange(0.25, 0.601, 0.05):
        for prior_start_weight in np.arange(0.20, 0.701, 0.05):
            for half_life in half_lives:
                result = evaluate(
                    training,
                    float(round(form_weight, 2)),
                    float(round(prior_start_weight, 2)),
                    float(half_life),
                )
                candidates.append(
                    {
                        "form": float(round(form_weight, 2)),
                        "prior_start": float(round(prior_start_weight, 2)),
                        "prior_half_life_minutes": half_life,
                        **result,
                    }
                )
    candidates.sort(key=lambda candidate: candidate["mae"])
    best = candidates[0]
    best_holdout = evaluate(
        holdout,
        best["form"],
        best["prior_start"],
        best["prior_half_life_minutes"],
    )

    report = {
        "data": {
            "prior_season": PRIOR_SEASON,
            "current_season": CURRENT_SEASON,
            "training_gameweeks": [1, 25],
            "holdout_gameweeks": [26, 38],
            "training_examples": int(len(training)),
            "holdout_examples": int(len(holdout)),
            "scored_players_only": True,
            "fixture_adjustment_included": False,
            "availability_model_evaluated": False,
        },
        "baseline": {
            "weights": baseline,
            "train": baseline_train,
            "holdout": baseline_holdout,
        },
        "calibrated": {
            "weights": {
                "form": best["form"],
                "points_per_game": 1.0 - best["form"],
                "prior_start": best["prior_start"],
                "prior_half_life_minutes": best["prior_half_life_minutes"],
            },
            "train": {key: best[key] for key in ("mae", "rmse", "spearman", "n")},
            "holdout": best_holdout,
        },
        "top_training_candidates": candidates[:5],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
