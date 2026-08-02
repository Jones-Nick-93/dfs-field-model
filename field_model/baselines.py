"""Transparent null models for testing whether lineup structure adds value."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contest import ContestField
from .core import SlateConfig, generate_weighted_lineups, ownership
from .diagnostics import (
    FieldComparison,
    ObservedFieldReport,
    compare_field_reports,
    observed_field_report,
)


def ownership_weighted_null(
    observed: ContestField,
    pool: pd.DataFrame,
    cfg: SlateConfig,
    *,
    seed: int = 41,
    ownership_floor: float = 0.002,
    weight_power: float = 1.0,
    random_walk_steps: int = 30,
) -> ContestField:
    """Generate a legal null field using observed marginal ownership weights.

    The sampler does not force its realized ownership to equal the target. That
    mismatch is intentional and is quantified by :func:`compare_to_null`.
    """

    if ownership_floor <= 0:
        raise ValueError("ownership_floor must be positive")
    if weight_power <= 0:
        raise ValueError("weight_power must be positive")
    observed.validate_against_pool(pool, cfg)
    target = ownership(observed.lineups, pool)
    weights = np.power(target.clip(lower=ownership_floor), weight_power)
    lineups = generate_weighted_lineups(
        pool,
        cfg,
        weights,
        observed.field_size,
        seed=seed,
        random_walk_steps=random_walk_steps,
    )
    frame = pd.DataFrame(
        {
            "entry_id": [f"null-{index:06d}" for index in range(len(lineups))],
            "lineup": lineups,
        }
    )
    return ContestField(frame, contest_id=f"{observed.contest_id or 'contest'}-null")


def compare_to_null(
    observed: ContestField,
    pool: pd.DataFrame,
    cfg: SlateConfig,
    **null_kwargs: object,
) -> tuple[ObservedFieldReport, ObservedFieldReport, FieldComparison]:
    """Generate and evaluate the ownership-weighted legal null field."""

    null = ownership_weighted_null(observed, pool, cfg, **null_kwargs)
    observed_report = observed_field_report(observed, pool, cfg)
    null_report = observed_field_report(null, pool, cfg)
    comparison = compare_field_reports(observed_report, null_report)
    return observed_report, null_report, comparison
