"""Observed-field diagnostics that are identifiable from contest lineups."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.stats import wasserstein_distance

from .contest import ContestField
from .core import (
    SlateConfig,
    effective_lineups,
    lineup_hhi,
    mean_jaccard,
    ownership,
)


@dataclass(frozen=True)
class ObservedFieldReport:
    """Auditable summary tables for one observed or simulated contest field."""

    summary: dict[str, object]
    entries: pd.DataFrame
    player_ownership: pd.Series
    pair_ownership: pd.DataFrame
    duplication_distribution: pd.DataFrame
    team_stack_distribution: pd.DataFrame
    position_shape_distribution: pd.DataFrame


@dataclass(frozen=True)
class FieldComparison:
    """Observed-versus-baseline calibration errors."""

    summary: dict[str, float]
    player_errors: pd.DataFrame
    pair_errors: pd.DataFrame


def observed_field_report(
    field: ContestField,
    pool: pd.DataFrame,
    cfg: SlateConfig,
    *,
    pair_min_ownership: float = 0.01,
) -> ObservedFieldReport:
    """Compute lineup-level diagnostics from a canonical contest field."""

    field.validate_against_pool(pool, cfg)
    lineups = field.lineups
    lookup = pool.set_index(pool["player_id"].astype(str), drop=False)
    lineup_counts = Counter(lineups)

    entries = field.entries.copy()
    entries["exact_dup_count"] = [lineup_counts[lineup] for lineup in lineups]
    entries["computed_salary_used"] = [
        float(lookup.loc[list(lineup), "salary"].sum()) for lineup in lineups
    ]
    entries["salary_remaining"] = cfg.salary_cap - entries["computed_salary_used"]
    if "salary_used" in entries:
        entries["salary_mismatch"] = (
            entries["salary_used"] - entries["computed_salary_used"]
        ).abs()

    exposure = ownership(lineups, pool)
    pair_table = _pair_ownership(lineups, pool, exposure, pair_min_ownership)
    duplicate_entries = entries["exact_dup_count"] > 1
    summary: dict[str, object] = {
        "contest_id": field.contest_id,
        "entries": field.field_size,
        "roster_size": field.roster_size,
        "unique_lineups": len(lineup_counts),
        "unique_lineup_pct": 100 * len(lineup_counts) / field.field_size,
        "lineup_hhi": lineup_hhi(lineups),
        "effective_lineups": effective_lineups(lineups),
        "most_duplicated_lineup": max(lineup_counts.values()),
        "duplicated_entry_pct": 100 * float(duplicate_entries.mean()),
        "mean_jaccard": mean_jaccard(lineups),
        "mean_salary_used": float(entries["computed_salary_used"].mean()),
        "median_salary_remaining": float(entries["salary_remaining"].median()),
        "p90_salary_remaining": float(entries["salary_remaining"].quantile(0.90)),
    }
    if "salary_mismatch" in entries:
        summary["salary_mismatch_entries"] = int(
            entries["salary_mismatch"].gt(0.01).sum()
        )
    if "account_id" in entries:
        account_counts = entries["account_id"].astype(str).value_counts()
        summary["accounts"] = int(len(account_counts))
        summary["max_entries_per_account"] = int(account_counts.max())
        summary["multi_entry_field_pct"] = 100 * float(
            entries["account_id"]
            .astype(str)
            .isin(account_counts[account_counts > 1].index)
            .mean()
        )
    if "score" in entries and entries["score"].notna().any():
        for quantile in (0.50, 0.95, 0.99, 1.00):
            label = (
                "winning_score" if quantile == 1 else f"score_p{int(quantile * 100)}"
            )
            summary[label] = float(entries["score"].quantile(quantile))

    duplicate_distribution = (
        entries["exact_dup_count"]
        .value_counts()
        .sort_index()
        .rename_axis("exact_dup_count")
        .rename("entries")
        .reset_index()
    )
    duplicate_distribution["entry_pct"] = (
        100 * duplicate_distribution["entries"] / field.field_size
    )
    stack_distribution = _categorical_distribution(
        [_max_team_stack(lineup, lookup) for lineup in lineups],
        "max_team_stack",
    )
    shape_distribution = _categorical_distribution(
        [_position_shape(lineup, lookup) for lineup in lineups],
        "position_shape",
    )
    return ObservedFieldReport(
        summary=summary,
        entries=entries,
        player_ownership=exposure,
        pair_ownership=pair_table,
        duplication_distribution=duplicate_distribution,
        team_stack_distribution=stack_distribution,
        position_shape_distribution=shape_distribution,
    )


def compare_field_reports(
    observed: ObservedFieldReport,
    baseline: ObservedFieldReport,
) -> FieldComparison:
    """Compare a generated baseline against observed lineup structure."""

    player = pd.concat(
        {
            "observed": observed.player_ownership,
            "baseline": baseline.player_ownership,
        },
        axis=1,
    ).fillna(0)
    player["error"] = player["baseline"] - player["observed"]
    player["abs_error"] = player["error"].abs()

    pair_columns = ["player_a", "player_b", "coownership"]
    observed_pairs = observed.pair_ownership[pair_columns].rename(
        columns={"coownership": "observed"}
    )
    baseline_pairs = baseline.pair_ownership[pair_columns].rename(
        columns={"coownership": "baseline"}
    )
    pair = observed_pairs.merge(
        baseline_pairs, on=["player_a", "player_b"], how="outer"
    ).fillna(0)
    pair["error"] = pair["baseline"] - pair["observed"]
    pair["abs_error"] = pair["error"].abs()

    observed_salary = observed.entries["salary_remaining"].to_numpy()
    baseline_salary = baseline.entries["salary_remaining"].to_numpy()
    observed_hhi = float(observed.summary["lineup_hhi"])
    baseline_hhi = float(baseline.summary["lineup_hhi"])
    summary = {
        "player_ownership_mae": float(player["abs_error"].mean()),
        "player_ownership_rmse": float(np.sqrt(np.mean(player["error"] ** 2))),
        "pair_ownership_mae": float(pair["abs_error"].mean()),
        "pair_ownership_rmse": float(np.sqrt(np.mean(pair["error"] ** 2))),
        "observed_lineup_hhi": observed_hhi,
        "baseline_lineup_hhi": baseline_hhi,
        "lineup_hhi_ratio": baseline_hhi / observed_hhi if observed_hhi else np.nan,
        "salary_remaining_wasserstein": float(
            wasserstein_distance(observed_salary, baseline_salary)
        ),
    }
    return FieldComparison(summary, player, pair)


def _pair_ownership(
    lineups: list[frozenset[str]],
    pool: pd.DataFrame,
    exposure: pd.Series,
    minimum: float,
) -> pd.DataFrame:
    output_columns = [
        "player_a",
        "player_b",
        "ownership_a",
        "ownership_b",
        "coownership",
        "independent_coownership",
        "excess_coownership",
        "coownership_lift",
    ]
    player_ids = pool["player_id"].astype(str).tolist()
    id_to_column = {player_id: column for column, player_id in enumerate(player_ids)}
    rows: list[int] = []
    columns: list[int] = []
    for row, lineup in enumerate(lineups):
        rows.extend([row] * len(lineup))
        columns.extend(id_to_column[player_id] for player_id in lineup)
    matrix = csr_matrix(
        (np.ones(len(rows), dtype=float), (rows, columns)),
        shape=(len(lineups), len(player_ids)),
    )
    coownership = (matrix.T @ matrix).toarray() / len(lineups)
    records: list[dict[str, object]] = []
    for first in range(len(player_ids)):
        own_first = float(exposure.loc[player_ids[first]])
        if own_first < minimum:
            continue
        for second in range(first + 1, len(player_ids)):
            own_second = float(exposure.loc[player_ids[second]])
            if own_second < minimum:
                continue
            observed = float(coownership[first, second])
            independent = own_first * own_second
            records.append(
                {
                    "player_a": player_ids[first],
                    "player_b": player_ids[second],
                    "ownership_a": own_first,
                    "ownership_b": own_second,
                    "coownership": observed,
                    "independent_coownership": independent,
                    "excess_coownership": observed - independent,
                    "coownership_lift": (
                        observed / independent if independent > 0 else np.nan
                    ),
                }
            )
    return pd.DataFrame.from_records(records, columns=output_columns)


def _max_team_stack(lineup: frozenset[str], lookup: pd.DataFrame) -> int:
    return int(lookup.loc[list(lineup), "team"].value_counts().max())


def _position_shape(lineup: frozenset[str], lookup: pd.DataFrame) -> str:
    counts = lookup.loc[list(lineup), "pos"].astype(str).value_counts()
    return "|".join(f"{pos}{counts[pos]}" for pos in sorted(counts.index))


def _categorical_distribution(values: list[object], name: str) -> pd.DataFrame:
    result = (
        pd.Series(values, name=name)
        .value_counts()
        .rename("entries")
        .rename_axis(name)
        .reset_index()
    )
    result["entry_pct"] = 100 * result["entries"] / len(values)
    return result
