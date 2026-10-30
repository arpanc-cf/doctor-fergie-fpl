# Score-weight backtest

**Data:** Vaastav's public FPL gameweek data for 2024/25 and 2025/26. The feature definitions are documented in the [dataset data dictionary](https://github.com/vaastav/Fantasy-Premier-League/blob/master/DATA_DICTIONARY.md). The reproducible calibration is in [scripts/backtest_score_weights.py](../scripts/backtest_score_weights.py).

## Method

The calibration reconstructs player features from gameweeks completed before each target gameweek. It uses 2024/25 points per 90 as the prior, tunes weights on 2025/26 gameweeks 1-25, and evaluates the selected settings on the untouched 2025/26 gameweeks 26-38 holdout. Archived expected-points values are excluded because they may reflect post-match information.

The score uses underlying form and current-season points per game. For players with a qualifying prior-season rate, that rate is blended in with a starting weight that decays by half every specified number of current-season minutes.

## Holdout results

The baseline is 70% underlying form, 30% points per game, and a fixed 30% previous-season prior. The calibrated candidate is 45% underlying form, 55% points per game, and a 25% previous-season prior that halves every 180 current-season minutes.

| Metric (2025/26 GW 26-38) | Baseline | Calibrated |
| --- | ---: | ---: |
| Player-game examples | 3,787 | 3,787 |
| Mean absolute error (points) | 2.323 | 2.209 |
| Root mean squared error (points) | 3.070 | 2.998 |
| Spearman rank correlation | 0.132 | 0.212 |

On this holdout, mean absolute error fell by about 4.9% and root mean squared error by about 2.3%; the rank correlation also improved.

## Limits

This is a player-score calibration, not a full manager-strategy backtest. It includes only players who appeared in the target gameweek, and it does not evaluate historical injury/availability decisions, fixture adjustments, transfer hits, budget constraints, or transfer outcomes. It supports a modest change to the underlying score weights; it does not establish guaranteed transfer or starting-XI improvements. Results come from one season's holdout and should be revisited as more completed seasons become available.
