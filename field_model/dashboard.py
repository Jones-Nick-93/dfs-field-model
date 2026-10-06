"""Framework-independent data preparation for the public dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

import numpy as np
import pandas as pd

from .baselines import ownership_weighted_null
from .contest import ContestField
from .core import (
    SlateConfig,
    segment_report,
)
from .diagnostics import (
    FieldComparison,
    ObservedFieldReport,
    compare_field_reports,
    observed_field_report,
)


@dataclass(frozen=True)
class DashboardAnalysis:
    """Complete analysis bundle consumed by presentation clients."""

    pool: pd.DataFrame
    config: SlateConfig
    field: ContestField
    observed: ObservedFieldReport
    baseline: ObservedFieldReport | None
    comparison: FieldComparison | None
    segment_summary: pd.DataFrame | None = None


def build_analysis(
    pool: pd.DataFrame,
    field: ContestField,
    config: SlateConfig,
    *,
    include_null: bool = True,
    null_seed: int = 44,
    null_walk_steps: int = 12,
) -> DashboardAnalysis:
    """Validate a field and prepare all dashboard diagnostics."""

    observed = observed_field_report(field, pool, config)
    if not include_null:
        return DashboardAnalysis(pool, config, field, observed, None, None)
    null_field = ownership_weighted_null(
        field,
        pool,
        config,
        seed=null_seed,
        random_walk_steps=null_walk_steps,
    )
    baseline = observed_field_report(null_field, pool, config)
    comparison = compare_field_reports(observed, baseline)
    return DashboardAnalysis(pool, config, field, observed, baseline, comparison)


def build_demo_analysis(
    *,
    seed: int = 7,
    entries_per_segment: int = 75,
) -> DashboardAnalysis:
    """Build a deterministic synthetic mixture for zero-setup exploration."""

    if entries_per_segment <= 0:
        raise ValueError("entries_per_segment must be positive")
    del seed  # The tracked fixture is deliberately deterministic.
    data = files("field_model").joinpath("demo_data")
    pool = pd.read_csv(data.joinpath("player_pool.csv"))
    observed_entries = pd.read_csv(data.joinpath("observed_entries.csv"))
    null_entries = pd.read_csv(data.joinpath("null_entries.csv"))
    available = observed_entries["segment_hypothesis"].value_counts().min()
    if entries_per_segment > available:
        raise ValueError(
            f"entries_per_segment cannot exceed tracked fixture size {available}"
        )
    observed_entries = (
        observed_entries.groupby("segment_hypothesis", sort=False)
        .head(entries_per_segment)
        .reset_index(drop=True)
    )
    null_entries = null_entries.head(2 * entries_per_segment).reset_index(drop=True)
    observed_field = _field_from_export(observed_entries, "synthetic-demo")
    null_field = _field_from_export(null_entries, "synthetic-demo-null")
    config = SlateConfig()
    observed = observed_field_report(observed_field, pool, config)
    baseline = observed_field_report(null_field, pool, config)
    comparison = compare_field_reports(observed, baseline)
    segment_groups = observed_entries.groupby("segment_hypothesis", sort=False)
    segments = pd.DataFrame(
        [
            segment_report(name, _parse_lineups(group["lineup"]), pool)
            for name, group in segment_groups
        ]
    )
    return DashboardAnalysis(
        pool,
        config,
        observed_field,
        observed,
        baseline,
        comparison,
        segments,
    )


def _field_from_export(frame: pd.DataFrame, contest_id: str) -> ContestField:
    result = frame.copy()
    result["lineup"] = _parse_lineups(result["lineup"])
    return ContestField(result, contest_id=contest_id)


def _parse_lineups(values: pd.Series) -> list[frozenset[str]]:
    return [frozenset(str(value).split("|")) for value in values]


def ownership_table(analysis: DashboardAnalysis) -> pd.DataFrame:
    """Return display-ready player ownership sorted from highest to lowest."""

    lookup = analysis.pool.set_index("player_id")
    result = lookup[["player", "team", "pos", "salary"]].copy()
    result["ownership_pct"] = 100 * analysis.observed.player_ownership
    if analysis.baseline is not None:
        result["null_ownership_pct"] = 100 * analysis.baseline.player_ownership
        result["ownership_gap_pp"] = (
            result["null_ownership_pct"] - result["ownership_pct"]
        )
    return result.reset_index().sort_values("ownership_pct", ascending=False)


def pair_signal_table(
    analysis: DashboardAnalysis, *, limit: int = 30
) -> pd.DataFrame:
    """Return the strongest positive co-ownership signals with player labels."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    pairs = analysis.observed.pair_ownership.copy()
    names = analysis.pool.set_index("player_id")["player"].astype(str)
    pairs["player_a_name"] = pairs["player_a"].map(names)
    pairs["player_b_name"] = pairs["player_b"].map(names)
    pairs["coownership_pct"] = 100 * pairs["coownership"]
    pairs["independent_pct"] = 100 * pairs["independent_coownership"]
    pairs["excess_pp"] = 100 * pairs["excess_coownership"]
    columns = [
        "player_a_name",
        "player_b_name",
        "coownership_pct",
        "independent_pct",
        "excess_pp",
        "coownership_lift",
    ]
    return pairs.sort_values("excess_coownership", ascending=False).head(limit)[
        columns
    ]


def salary_distribution(analysis: DashboardAnalysis) -> pd.DataFrame:
    """Return observed and null salary-remaining observations for charts."""

    frames = [
        analysis.observed.entries[["salary_remaining"]].assign(field="observed")
    ]
    if analysis.baseline is not None:
        frames.append(
            analysis.baseline.entries[["salary_remaining"]].assign(field="null")
        )
    return pd.concat(frames, ignore_index=True)


def duplication_comparison(analysis: DashboardAnalysis) -> pd.DataFrame:
    """Return aligned observed and null exact-duplication distributions."""

    observed = analysis.observed.duplication_distribution[
        ["exact_dup_count", "entry_pct"]
    ].rename(columns={"entry_pct": "observed_pct"})
    if analysis.baseline is None:
        return observed
    baseline = analysis.baseline.duplication_distribution[
        ["exact_dup_count", "entry_pct"]
    ].rename(columns={"entry_pct": "null_pct"})
    return observed.merge(baseline, on="exact_dup_count", how="outer").fillna(0)


def lineup_detail(analysis: DashboardAnalysis, entry_id: str) -> tuple[pd.DataFrame, dict[str, object]]:
    """Return roster rows and diagnostics for one observed entry."""

    matches = analysis.observed.entries.loc[
        analysis.observed.entries["entry_id"].astype(str).eq(str(entry_id))
    ]
    if matches.empty:
        raise ValueError(f"unknown entry_id: {entry_id}")
    entry = matches.iloc[0]
    lineup = entry["lineup"]
    roster = analysis.pool.set_index("player_id", drop=False).loc[list(lineup)].copy()
    roster = roster[["player_id", "player", "team", "pos", "salary", "consensus"]]
    roster = roster.sort_values(["pos", "salary"], ascending=[True, False])
    max_stack = int(roster["team"].value_counts().max())
    diagnostics: dict[str, object] = {
        "salary_used": int(entry["computed_salary_used"]),
        "salary_remaining": int(entry["salary_remaining"]),
        "exact_dup_count": int(entry["exact_dup_count"]),
        "max_team_stack": max_stack,
        "consensus_total": float(roster["consensus"].sum()),
    }
    return roster.reset_index(drop=True), diagnostics


def comparison_cards(analysis: DashboardAnalysis) -> list[dict[str, str]]:
    """Translate null-comparison metrics into compact UI cards."""

    if analysis.comparison is None:
        return []
    values = analysis.comparison.summary
    ratio = values["lineup_hhi_ratio"]
    return [
        {
            "label": "Null / observed HHI",
            "value": f"{ratio:.2f}×" if np.isfinite(ratio) else "n/a",
            "help": "1.00 means the ownership-only null matches observed lineup concentration.",
        },
        {
            "label": "Player ownership RMSE",
            "value": f"{100 * values['player_ownership_rmse']:.2f} pp",
            "help": "Realized marginal mismatch; lower is better.",
        },
        {
            "label": "Pair ownership RMSE",
            "value": f"{100 * values['pair_ownership_rmse']:.2f} pp",
            "help": "Joint player-pair mismatch; lower is better.",
        },
        {
            "label": "Salary distance",
            "value": f"${values['salary_remaining_wasserstein']:,.0f}",
            "help": "Wasserstein distance between salary-remaining distributions.",
        },
    ]
