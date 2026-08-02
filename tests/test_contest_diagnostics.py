from __future__ import annotations

import pandas as pd
import pytest

from field_model import (
    ContestField,
    SlateConfig,
    compare_to_null,
    contest_from_draftkings,
    contest_from_long,
    contest_from_wide,
    generate_weighted_choice,
    is_legal_lineup,
    near_optimal_lineups,
    observed_field_report,
    optimize,
    synthetic_pool,
)


@pytest.fixture
def cfg() -> SlateConfig:
    return SlateConfig()


@pytest.fixture
def pool() -> pd.DataFrame:
    return synthetic_pool(n_teams=6, seed=9)


def test_wide_and_long_ingestion_match() -> None:
    wide = pd.DataFrame(
        {
            "entry": ["e1", "e2"],
            "player1": ["a", "a"],
            "player2": ["b", "c"],
            "points": [10.5, 12.0],
        }
    )
    wide_field = contest_from_wide(
        wide,
        entry_id_column="entry",
        metadata_columns={"score": "points"},
    )
    long = pd.DataFrame(
        {
            "entry": ["e1", "e1", "e2", "e2"],
            "player": ["a", "b", "a", "c"],
            "points": [10.5, 10.5, 12.0, 12.0],
        }
    )
    long_field = contest_from_long(
        long,
        entry_id_column="entry",
        player_id_column="player",
        metadata_columns={"score": "points"},
    )
    assert wide_field.lineups == long_field.lineups
    assert wide_field.entries["score"].tolist() == [10.5, 12.0]
    assert long_field.entries["score"].tolist() == [10.5, 12.0]


def test_long_ingestion_rejects_inconsistent_metadata() -> None:
    frame = pd.DataFrame(
        {
            "entry_id": ["e1", "e1"],
            "player_id": ["a", "b"],
            "score": [1, 2],
        }
    )
    with pytest.raises(ValueError, match="varies"):
        contest_from_long(frame, metadata_columns={"score": "score"})


def test_draftkings_parser_resolves_names_to_stable_ids(
    pool: pd.DataFrame, cfg: SlateConfig
) -> None:
    lineup = optimize(pool, "consensus", cfg)
    assert lineup is not None
    selected = pool.set_index("player_id", drop=False).loc[list(lineup)]
    ordered_ids: list[str] = []
    slots: list[str] = []
    remaining = set(lineup)
    for pos, minimum in cfg.position_min.items():
        ids = selected.loc[selected["pos"].eq(pos), "player_id"].tolist()
        ordered_ids.extend(ids[:minimum])
        slots.extend([pos] * minimum)
        remaining -= set(ids[:minimum])
    ordered_ids.extend(sorted(remaining))
    slots.extend(["UTIL"] * len(remaining))
    text = " ".join(
        item for pair in zip(slots, ordered_ids, strict=True) for item in pair
    )
    frame = pd.DataFrame({"EntryId": ["dk-1"], "Lineup": [text]})
    field = contest_from_draftkings(frame, pool, slots)
    assert field.lineups == [lineup]


def test_observed_report_measures_exact_duplication_and_structure(
    pool: pd.DataFrame, cfg: SlateConfig
) -> None:
    lineups = generate_weighted_choice(pool, cfg, 18, seed=22)
    lineups[:3] = [lineups[0]] * 3
    entries = pd.DataFrame(
        {
            "entry_id": [f"e-{index}" for index in range(len(lineups))],
            "account_id": [f"a-{index // 2}" for index in range(len(lineups))],
            "lineup": lineups,
            "score": list(range(len(lineups))),
        }
    )
    field = ContestField(entries, contest_id="test")
    report = observed_field_report(field, pool, cfg)
    assert report.summary["entries"] == 18
    assert report.summary["most_duplicated_lineup"] >= 3
    assert report.summary["duplicated_entry_pct"] > 0
    assert report.summary["winning_score"] == 17
    assert report.summary["max_entries_per_account"] == 2
    assert not report.pair_ownership.empty
    assert report.entries["salary_remaining"].ge(0).all()
    assert report.team_stack_distribution["entries"].sum() == 18
    assert report.position_shape_distribution["entries"].sum() == 18


def test_ownership_null_is_legal_and_comparable(
    pool: pd.DataFrame, cfg: SlateConfig
) -> None:
    observed_lineups = generate_weighted_choice(pool, cfg, 20, seed=31)
    observed = ContestField(
        pd.DataFrame(
            {
                "entry_id": [f"obs-{index}" for index in range(20)],
                "lineup": observed_lineups,
            }
        ),
        contest_id="small",
    )
    observed_report, null_report, comparison = compare_to_null(
        observed,
        pool,
        cfg,
        seed=32,
        random_walk_steps=10,
    )
    assert observed_report.summary["entries"] == 20
    assert null_report.summary["entries"] == 20
    assert all(
        is_legal_lineup(lineup, pool, cfg) for lineup in null_report.entries["lineup"]
    )
    assert comparison.summary["player_ownership_rmse"] >= 0
    assert comparison.summary["pair_ownership_rmse"] >= 0


def test_near_optimal_menu_is_unique_legal_and_score_ordered(
    pool: pd.DataFrame, cfg: SlateConfig
) -> None:
    menu = near_optimal_lineups(pool, "consensus", cfg, 10)
    assert len(menu) == 10
    assert len(set(menu)) == 10
    assert all(is_legal_lineup(lineup, pool, cfg) for lineup in menu)
    scores = [
        pool.set_index("player_id").loc[list(lineup), "consensus"].sum()
        for lineup in menu
    ]
    assert scores == sorted(scores, reverse=True)
