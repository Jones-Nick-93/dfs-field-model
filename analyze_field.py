"""CLI for validating and diagnosing an observed contest export."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from field_model import (
    SlateConfig,
    compare_field_reports,
    load_draftkings_csv,
    load_long_csv,
    load_wide_csv,
    observed_field_report,
    ownership_weighted_null,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a DFS contest export and write lineup-level diagnostics."
    )
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--entries", required=True, type=Path)
    parser.add_argument(
        "--format", choices=("wide", "long", "draftkings"), default="wide"
    )
    parser.add_argument("--contest-id")
    parser.add_argument("--entry-id-column", default="entry_id")
    parser.add_argument("--player-id-column", default="player_id")
    parser.add_argument("--lineup-column", default="Lineup")
    parser.add_argument(
        "--player-columns",
        help="Comma-separated player columns for wide format; auto-detected by default.",
    )
    parser.add_argument(
        "--roster-slots",
        help="Ordered comma-separated slots required for DraftKings format.",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="CANONICAL=SOURCE",
        help="Map score, rank, payout, salary_used, or account_id; repeat as needed.",
    )
    parser.add_argument("--roster-size", type=int, required=True)
    parser.add_argument("--salary-cap", type=int, required=True)
    parser.add_argument(
        "--position-min",
        required=True,
        help="Comma-separated minimums, for example GK=1,D=2,M=2,F=2.",
    )
    parser.add_argument(
        "--flex-positions",
        default="",
        help="Comma-separated positions eligible for remaining roster slots.",
    )
    parser.add_argument("--max-per-team", type=int, required=True)
    parser.add_argument("--min-salary-spend", type=int, default=0)
    parser.add_argument("--with-null", action="store_true")
    parser.add_argument("--null-seed", type=int, default=41)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    contest_id = args.contest_id or args.entries.stem
    cfg = SlateConfig(
        roster_size=args.roster_size,
        salary_cap=args.salary_cap,
        position_min=_parse_mapping(args.position_min, value_type=int),
        flex_positions=tuple(_split_csv(args.flex_positions)),
        max_per_team=args.max_per_team,
        min_salary_spend=args.min_salary_spend,
    )
    cfg.validate()
    pool = pd.read_csv(args.pool)
    metadata = _parse_metadata(args.metadata)

    if args.format == "wide":
        player_columns = (
            _split_csv(args.player_columns) if args.player_columns else None
        )
        field = load_wide_csv(
            args.entries,
            player_columns=player_columns,
            entry_id_column=args.entry_id_column,
            metadata_columns=metadata,
            contest_id=contest_id,
        )
    elif args.format == "long":
        field = load_long_csv(
            args.entries,
            entry_id_column=args.entry_id_column,
            player_id_column=args.player_id_column,
            metadata_columns=metadata,
            contest_id=contest_id,
        )
    else:
        if not args.roster_slots:
            raise ValueError("--roster-slots is required for DraftKings format")
        field = load_draftkings_csv(
            args.entries,
            pool,
            _split_csv(args.roster_slots),
            lineup_column=args.lineup_column,
            entry_id_column=args.entry_id_column,
            metadata_columns=metadata,
            contest_id=contest_id,
        )

    report = observed_field_report(field, pool, cfg)
    output_dir = args.output_dir or Path("outputs") / contest_id
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_report(report, output_dir, prefix="observed")

    if args.with_null:
        null_field = ownership_weighted_null(field, pool, cfg, seed=args.null_seed)
        null_report = observed_field_report(null_field, pool, cfg)
        comparison = compare_field_reports(report, null_report)
        _write_report(null_report, output_dir, prefix="null")
        _write_json(output_dir / "comparison_summary.json", comparison.summary)
        comparison.player_errors.to_csv(
            output_dir / "comparison_player_errors.csv", index=True
        )
        comparison.pair_errors.to_csv(
            output_dir / "comparison_pair_errors.csv", index=False
        )

    print(json.dumps(_json_ready(report.summary), indent=2, sort_keys=True))
    print(f"\nWrote diagnostics to {output_dir.resolve()}")


def _write_report(report: object, output_dir: Path, prefix: str) -> None:
    _write_json(output_dir / f"{prefix}_summary.json", report.summary)
    entries = report.entries.copy()
    entries["lineup"] = entries["lineup"].map(lambda lineup: "|".join(sorted(lineup)))
    entries.to_csv(output_dir / f"{prefix}_entries.csv", index=False)
    report.player_ownership.rename("ownership").to_csv(
        output_dir / f"{prefix}_player_ownership.csv", index=True
    )
    report.pair_ownership.to_csv(
        output_dir / f"{prefix}_pair_ownership.csv", index=False
    )
    report.duplication_distribution.to_csv(
        output_dir / f"{prefix}_duplication_distribution.csv", index=False
    )
    report.team_stack_distribution.to_csv(
        output_dir / f"{prefix}_team_stack_distribution.csv", index=False
    )
    report.position_shape_distribution.to_csv(
        output_dir / f"{prefix}_position_shape_distribution.csv", index=False
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(_json_ready(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _parse_metadata(values: Sequence[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"metadata mapping must contain '=': {value!r}")
        canonical, source = value.split("=", 1)
        output[canonical.strip()] = source.strip()
    return output


def _parse_mapping(value: str, value_type: type = str) -> dict[str, object]:
    output: dict[str, object] = {}
    for item in _split_csv(value):
        if "=" not in item:
            raise ValueError(f"mapping item must contain '=': {item!r}")
        key, raw_value = item.split("=", 1)
        output[key.strip()] = value_type(raw_value.strip())
    return output


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    main()
