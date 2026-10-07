"""Controlled teaching example and portable, deterministic analysis exports."""

from __future__ import annotations

import json
from dataclasses import asdict
from io import BytesIO
from itertools import combinations
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pandas as pd

from .contest import ContestField
from .core import SlateConfig
from .dashboard import DashboardAnalysis, ownership_table, pair_signal_table
from .diagnostics import observed_field_report


def controlled_fields() -> tuple[DashboardAnalysis, DashboardAnalysis]:
    """Two legal 12-entry fields with identical 50% player marginals."""
    pool = pd.DataFrame(
        [
            dict(
                player_id=p,
                player=p,
                team=p,
                pos="UTIL",
                salary=100,
                true_mean=1.0,
                consensus=1.0,
                fame=0.0,
                recency=0.0,
            )
            for p in "ABCD"
        ]
    )
    config = SlateConfig(
        roster_size=2,
        salary_cap=200,
        position_min={"UTIL": 2},
        flex_positions=(),
        max_per_team=1,
    )
    constructions = {
        "Clustered": [frozenset("AB")] * 6 + [frozenset("CD")] * 6,
        "Spread": [frozenset(pair) for pair in combinations("ABCD", 2)] * 2,
    }
    analyses = []
    for name, lineups in constructions.items():
        field = ContestField(
            pd.DataFrame(
                {"entry_id": [f"{name}-{i}" for i in range(12)], "lineup": lineups}
            ),
            contest_id=name,
        )
        report = observed_field_report(field, pool, config)
        analyses.append(DashboardAnalysis(pool, config, field, report, None, None))
    return tuple(analyses)


def controlled_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Field": analysis.field.contest_id,
                "Entries": 12,
                "Ownership per player": "50%",
                "Unique lineups": analysis.observed.summary["unique_lineups"],
                "Lineup HHI": analysis.observed.summary["lineup_hhi"],
                "Effective lineups": analysis.observed.summary["effective_lineups"],
            }
            for analysis in controlled_fields()
        ]
    )


def controlled_bundle() -> bytes:
    """A complete paired case study, including the actual synthetic lineups."""
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        _write_member(
            archive, "comparison.csv", controlled_summary().to_csv(index=False)
        )
        _write_member(
            archive,
            "README.md",
            "# Same ownership, different field\n\n"
            "Every player is at 50% ownership in both 12-entry fields.\n"
            "Clustered HHI = 0.500; spread HHI = 1/6.\n"
            "The bundled lineups are entirely synthetic.\n",
        )
        for analysis in controlled_fields():
            name = analysis.field.contest_id.lower()
            _write_member(
                archive,
                f"{name}-entries.csv",
                wide_entries(analysis).to_csv(index=False),
            )
            _write_member(
                archive,
                f"{name}-analysis.zip",
                report_bundle(analysis, source=f"Controlled synthetic: {name}"),
            )
    return buffer.getvalue()


def wide_entries(analysis: DashboardAnalysis) -> pd.DataFrame:
    """Export roster IDs only; deliberately exclude account/score metadata."""
    return pd.DataFrame(
        [
            {
                "entry_id": str(row.entry_id),
                **{
                    f"player{i + 1}": player
                    for i, player in enumerate(sorted(row.lineup))
                },
            }
            for row in analysis.field.entries.itertuples()
        ]
    )


def report_bundle(analysis: DashboardAnalysis, *, source: str) -> bytes:
    """Export aggregate evidence; omit user identifiers, filenames, and rosters."""
    summary = {
        k: v
        for k, v in analysis.observed.summary.items()
        if k not in {"contest_id"} and not k.startswith("account")
    }
    payload = {
        "schema_version": 1,
        "source": source,
        "input_summary": {
            "players": len(analysis.pool),
            "entries": analysis.field.field_size,
        },
        "roster_rules": asdict(analysis.config),
        "metrics": summary,
        "baseline_error": analysis.comparison.summary if analysis.comparison else None,
        "assumptions": [
            "Lineups validated against supplied roster rules.",
            "Ownership null is approximate; inspect realized marginal error.",
            "Structural diagnostics do not establish causality or profitability.",
        ],
    }
    note = (
        "# DFS Field Lab analysis\n\n"
        f"Source: {source}\n\nEntries: {analysis.field.field_size}\n\n"
        f"Lineup HHI: {summary['lineup_hhi']:.6f}\n\n"
        "HHI is the sum of squared exact-lineup frequencies. Its inverse is the effective lineup count.\n\n"
        "Inspect baseline ownership error before interpreting a structural gap. "
        "These diagnostics do not validate entrant intent, future outcomes, or profit.\n\n"
        "The export omits account metadata, upload filenames, and individual entry rosters. "
        "Player labels and aggregate ownership remain: review before sharing.\n"
    )
    files = {
        "README.md": note,
        "analysis.json": json.dumps(
            payload, indent=2, default=_json_scalar, allow_nan=False
        )
        + "\n",
        "ownership.csv": ownership_table(analysis).to_csv(index=False),
        "pair_structure.csv": pair_signal_table(analysis).to_csv(index=False),
        "duplication.csv": analysis.observed.duplication_distribution.to_csv(
            index=False
        ),
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            _write_member(archive, name, content)
    return buffer.getvalue()


def _write_member(archive: ZipFile, name: str, content: str | bytes) -> None:
    info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    archive.writestr(info, content)


def _json_scalar(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
