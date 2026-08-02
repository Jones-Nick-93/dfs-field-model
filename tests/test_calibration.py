from __future__ import annotations

import pandas as pd
import pytest

from field_model import (
    SharedMenuConfig,
    SlateConfig,
    build_shared_menu,
    calibrate_shared_menu,
    fit_mixture_weights,
    generate_shared_menu,
    synthetic_pool,
)


def test_mixture_weight_fit_recovers_identifiable_weights() -> None:
    index = pd.Index(["a", "b", "c"])
    first = pd.Series([0.8, 0.2, 0.5], index=index)
    second = pd.Series([0.2, 0.8, 0.5], index=index)
    observed = 0.7 * first + 0.3 * second
    fit = fit_mixture_weights(observed, {"first": first, "second": second})
    assert fit.weights["first"] == pytest.approx(0.7, abs=1e-5)
    assert fit.weights["second"] == pytest.approx(0.3, abs=1e-5)
    assert fit.rmse == pytest.approx(0, abs=1e-8)
    assert fit.locally_identifiable_design


def test_mixture_weight_fit_flags_collinear_segments() -> None:
    index = pd.Index(["a", "b", "c"])
    segment = pd.Series([0.2, 0.4, 0.6], index=index)
    fit = fit_mixture_weights(segment, {"copy_one": segment, "copy_two": segment})
    assert fit.rmse == pytest.approx(0, abs=1e-8)
    assert fit.design_rank == 1
    assert not fit.locally_identifiable_design


def test_shared_menu_calibration_reports_menu_coverage_and_trials() -> None:
    pool = synthetic_pool(n_teams=6, seed=61)
    cfg = SlateConfig()
    behavior = SharedMenuConfig(
        menu_size=6,
        projection_noise_sd=0.35,
        choice_temperature=0.45,
    )
    menu = build_shared_menu(pool, cfg, behavior)
    observed = generate_shared_menu(
        pool, cfg, 250, behavior=behavior, seed=62, menu=menu
    )
    result = calibrate_shared_menu(
        observed,
        pool,
        cfg,
        menu,
        projection_noise_grid=(0.2, 0.5),
        choice_temperature_grid=(0.25, 0.7),
        simulation_entries=500,
        seed=63,
    )
    assert result.menu_coverage == 1.0
    assert result.observed_entries_on_menu == 250
    assert len(result.trials) == 4
    assert result.trials["loss"].is_monotonic_increasing
    assert result.best_config.menu_size == len(menu)
