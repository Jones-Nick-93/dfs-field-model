"""Calibration utilities with explicit identification diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.spatial.distance import jensenshannon

from .core import (
    Lineup,
    SharedMenuConfig,
    SlateConfig,
    generate_shared_menu,
    lineup_hhi,
    ownership,
)


@dataclass(frozen=True)
class MixtureWeightFit:
    """Constrained marginal-ownership mixture fit."""

    weights: pd.Series
    fitted_ownership: pd.Series
    residuals: pd.Series
    rmse: float
    design_rank: int
    condition_number: float
    locally_identifiable_design: bool


@dataclass(frozen=True)
class SharedMenuCalibrationResult:
    """Grid fit of a shared-menu choice model to observed lineup frequencies."""

    best_config: SharedMenuConfig
    menu_coverage: float
    observed_entries_on_menu: int
    trials: pd.DataFrame


def fit_mixture_weights(
    observed_ownership: pd.Series,
    segment_ownership: Mapping[str, pd.Series],
    *,
    ridge: float = 0.0,
) -> MixtureWeightFit:
    """Fit nonnegative segment weights that sum to one.

    Rank and condition diagnostics are returned because a low residual does not
    imply that aggregate ownership uniquely identifies the behavioral mixture.
    """

    if len(segment_ownership) < 2:
        raise ValueError("at least two candidate segments are required")
    if ridge < 0:
        raise ValueError("ridge cannot be negative")
    names = list(segment_ownership)
    common_index = observed_ownership.index
    columns: list[np.ndarray] = []
    for name in names:
        series = segment_ownership[name].reindex(common_index)
        if series.isna().any():
            raise ValueError(f"segment {name!r} is missing player ownership values")
        columns.append(series.to_numpy(dtype=float))
    design = np.column_stack(columns)
    target = observed_ownership.to_numpy(dtype=float)
    if not np.isfinite(design).all() or not np.isfinite(target).all():
        raise ValueError("ownership inputs must be finite")

    center = np.full(len(names), 1 / len(names))

    def objective(weights: np.ndarray) -> float:
        residual = design @ weights - target
        return float(residual @ residual + ridge * np.square(weights - center).sum())

    result = minimize(
        objective,
        x0=center,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * len(names),
        constraints={"type": "eq", "fun": lambda weights: weights.sum() - 1.0},
        options={"ftol": 1e-12, "maxiter": 2_000},
    )
    if not result.success:
        raise RuntimeError(f"mixture optimization failed: {result.message}")
    fitted_values = design @ result.x
    residual_values = fitted_values - target
    singular_values = np.linalg.svd(design, compute_uv=False)
    tolerance = max(design.shape) * np.finfo(float).eps * singular_values[0]
    rank = int((singular_values > tolerance).sum())
    condition = (
        float(singular_values[0] / singular_values[-1])
        if singular_values[-1] > tolerance
        else float("inf")
    )
    # The equality constraint removes one degree of freedom. Full column rank is
    # a useful local diagnostic, though behavioral identification still requires
    # joint lineup and score information.
    locally_identified = (
        rank == len(names) and np.isfinite(condition) and condition < 1e6
    )
    weights = pd.Series(result.x, index=names, name="weight")
    fitted = pd.Series(fitted_values, index=common_index, name="fitted_ownership")
    residuals = pd.Series(residual_values, index=common_index, name="residual")
    return MixtureWeightFit(
        weights=weights,
        fitted_ownership=fitted,
        residuals=residuals,
        rmse=float(np.sqrt(np.mean(np.square(residual_values)))),
        design_rank=rank,
        condition_number=condition,
        locally_identifiable_design=locally_identified,
    )


def calibrate_shared_menu(
    observed_entries: Sequence[Lineup],
    pool: pd.DataFrame,
    cfg: SlateConfig,
    menu: Sequence[Lineup],
    *,
    projection_noise_grid: Sequence[float] = (0.15, 0.35, 0.70),
    choice_temperature_grid: Sequence[float] = (0.20, 0.45, 0.90),
    simulation_entries: int = 4_000,
    seed: int = 71,
) -> SharedMenuCalibrationResult:
    """Fit menu-choice parameters to entries that exactly fall on the menu.

    ``menu_coverage`` is the first model check. A low value means tuning choice
    parameters cannot rescue the menu hypothesis and the generator should be
    expanded or rejected.
    """

    if not observed_entries:
        raise ValueError("observed_entries cannot be empty")
    if not menu:
        raise ValueError("menu cannot be empty")
    if simulation_entries <= 0:
        raise ValueError("simulation_entries must be positive")
    if not projection_noise_grid or not choice_temperature_grid:
        raise ValueError("calibration grids cannot be empty")
    menu = list(dict.fromkeys(menu))
    menu_index = {lineup: index for index, lineup in enumerate(menu)}
    observed_on_menu = [lineup for lineup in observed_entries if lineup in menu_index]
    if not observed_on_menu:
        raise ValueError("none of the observed entries occur on the proposed menu")
    observed_counts = np.bincount(
        [menu_index[lineup] for lineup in observed_on_menu], minlength=len(menu)
    ).astype(float)
    observed_probability = observed_counts / observed_counts.sum()
    observed_hhi = lineup_hhi(observed_on_menu)
    observed_exposure = ownership(observed_on_menu, pool)

    records: list[dict[str, float]] = []
    for trial, (noise, temperature) in enumerate(
        product(projection_noise_grid, choice_temperature_grid)
    ):
        config = SharedMenuConfig(
            menu_size=len(menu),
            projection_noise_sd=float(noise),
            choice_temperature=float(temperature),
        )
        simulated = generate_shared_menu(
            pool,
            cfg,
            simulation_entries,
            behavior=config,
            seed=seed + trial,
            menu=menu,
        )
        simulated_counts = np.bincount(
            [menu_index[lineup] for lineup in simulated], minlength=len(menu)
        ).astype(float)
        simulated_probability = simulated_counts / simulated_counts.sum()
        js_divergence = float(
            jensenshannon(
                observed_probability + 1e-12,
                simulated_probability + 1e-12,
                base=2,
            )
            ** 2
        )
        simulated_exposure = ownership(simulated, pool)
        ownership_rmse = float(
            np.sqrt(np.mean(np.square(simulated_exposure - observed_exposure)))
        )
        hhi_error = abs(lineup_hhi(simulated) - observed_hhi)
        # Distributional fit is primary. Marginal and HHI terms stabilize finite
        # samples and keep their units visible in the trial table.
        loss = js_divergence + ownership_rmse + hhi_error
        records.append(
            {
                "projection_noise_sd": float(noise),
                "choice_temperature": float(temperature),
                "js_divergence": js_divergence,
                "ownership_rmse": ownership_rmse,
                "hhi_absolute_error": hhi_error,
                "loss": loss,
            }
        )
    trials = pd.DataFrame(records).sort_values(
        ["loss", "js_divergence"], ignore_index=True
    )
    best = trials.iloc[0]
    best_config = SharedMenuConfig(
        menu_size=len(menu),
        projection_noise_sd=float(best["projection_noise_sd"]),
        choice_temperature=float(best["choice_temperature"]),
    )
    return SharedMenuCalibrationResult(
        best_config=best_config,
        menu_coverage=len(observed_on_menu) / len(observed_entries),
        observed_entries_on_menu=len(observed_on_menu),
        trials=trials,
    )
