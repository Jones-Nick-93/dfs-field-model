from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from field_model import (
    SharedMenuConfig,
    SlateConfig,
    WeightedChoiceConfig,
    build_shared_menu,
    duplication_count,
    effective_lineups,
    generate_shared_menu,
    generate_weighted_choice,
    lineup_hhi,
    optimize,
    ownership,
    ownership_source_share,
    synthetic_pool,
    top_n_lineups,
    validate_pool,
)


@pytest.fixture
def cfg() -> SlateConfig:
    return SlateConfig()


@pytest.fixture
def pool() -> pd.DataFrame:
    result = synthetic_pool(n_teams=6, seed=4)
    result.index = np.arange(100, 100 + 3 * len(result), 3)
    return result


def assert_legal(lineup: frozenset[str], pool: pd.DataFrame, cfg: SlateConfig) -> None:
    selected = pool.set_index("player_id").loc[list(lineup)]
    assert len(lineup) == cfg.roster_size
    assert selected["salary"].sum() <= cfg.salary_cap
    assert selected["salary"].sum() >= cfg.min_salary_spend
    assert selected["team"].value_counts().max() <= cfg.max_per_team
    counts = selected["pos"].value_counts()
    for pos, minimum in cfg.position_min.items():
        assert counts.get(pos, 0) >= minimum
        maximum = minimum + (cfg.n_flex if pos in cfg.flex_positions else 0)
        assert counts.get(pos, 0) <= maximum


def test_optimizer_uses_stable_ids_with_noncontiguous_index(
    pool: pd.DataFrame, cfg: SlateConfig
) -> None:
    lineup = optimize(pool, "consensus", cfg)
    assert lineup is not None
    assert all(isinstance(player_id, str) for player_id in lineup)
    assert_legal(lineup, pool, cfg)


def test_top_n_lineups_are_unique(pool: pd.DataFrame, cfg: SlateConfig) -> None:
    lineups = top_n_lineups(pool, "consensus", cfg, 5)
    assert len(lineups) == 5
    assert len(set(lineups)) == 5
    assert all(len(lineup) == cfg.roster_size for lineup in lineups)


def test_generators_are_reproducible_and_return_requested_count(
    pool: pd.DataFrame, cfg: SlateConfig
) -> None:
    shared_menu_config = SharedMenuConfig(menu_size=6)
    weighted_choice_config = WeightedChoiceConfig(random_walk_steps=15)
    menu = build_shared_menu(pool, cfg, shared_menu_config)
    shared_menu_first = generate_shared_menu(
        pool, cfg, 20, behavior=shared_menu_config, seed=10, menu=menu
    )
    shared_menu_second = generate_shared_menu(
        pool, cfg, 20, behavior=shared_menu_config, seed=10, menu=menu
    )
    weighted_choice_first = generate_weighted_choice(
        pool, cfg, 20, behavior=weighted_choice_config, seed=20
    )
    weighted_choice_second = generate_weighted_choice(
        pool, cfg, 20, behavior=weighted_choice_config, seed=20
    )
    assert shared_menu_first == shared_menu_second
    assert weighted_choice_first == weighted_choice_second
    assert len(shared_menu_first) == 20
    assert len(weighted_choice_first) == 20
    assert all(len(lineup) == cfg.roster_size for lineup in weighted_choice_first)


def test_ownership_sums_to_roster_size(pool: pd.DataFrame, cfg: SlateConfig) -> None:
    entries = generate_weighted_choice(pool, cfg, 25, seed=8)
    exposure = ownership(entries, pool)
    assert exposure.sum() == pytest.approx(cfg.roster_size)
    assert exposure.index.equals(
        pd.Index(pool["player_id"].astype(str), name="player_id")
    )


def test_lineup_concentration_metrics() -> None:
    first = frozenset({"a", "b"})
    second = frozenset({"c", "d"})
    entries = [first, first, first, second]
    assert lineup_hhi(entries) == pytest.approx(0.625)
    assert effective_lineups(entries) == pytest.approx(1.6)
    assert duplication_count(first, entries) == 3


def test_source_share_is_weighted_and_bounded() -> None:
    segment = pd.Series([0.8, 0.1], index=["a", "b"])
    aggregate = pd.Series([0.5, 0.2], index=["a", "b"])
    share = ownership_source_share(segment, aggregate, segment_weight=0.5)
    assert share.loc["a"] == pytest.approx(0.8)
    assert share.loc["b"] == pytest.approx(0.25)
    assert share.between(0, 1).all()


def test_validation_rejects_duplicate_player_ids(
    pool: pd.DataFrame,
) -> None:
    broken = pool.copy()
    broken.iloc[1, broken.columns.get_loc("player_id")] = broken.iloc[0]["player_id"]
    with pytest.raises(ValueError, match="unique"):
        validate_pool(broken)


def test_validation_rejects_impossible_position_minimums() -> None:
    with pytest.raises(ValueError, match="exceed"):
        SlateConfig(
            roster_size=2,
            position_min={"GK": 1, "D": 2},
            flex_positions=(),
        ).validate()
