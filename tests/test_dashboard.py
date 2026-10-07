from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from field_model import contest_from_wide
from field_model.dashboard import (
    build_demo_analysis,
    comparison_cards,
    duplication_comparison,
    lineup_detail,
    ownership_table,
    pair_signal_table,
    salary_distribution,
)
from field_model.interview import report_bundle, wide_entries


@pytest.fixture(scope="module")
def demo_analysis():
    return build_demo_analysis(seed=17, entries_per_segment=25)


def test_demo_analysis_is_complete_and_reproducible(demo_analysis) -> None:
    repeated = build_demo_analysis(seed=17, entries_per_segment=25)
    assert demo_analysis.observed.summary == repeated.observed.summary
    assert demo_analysis.observed.summary["entries"] == 50
    assert demo_analysis.baseline is not None
    assert demo_analysis.comparison is not None
    assert len(demo_analysis.segment_summary) == 2


def test_dashboard_tables_preserve_report_totals(demo_analysis) -> None:
    ownership = ownership_table(demo_analysis)
    pairs = pair_signal_table(demo_analysis, limit=10)
    salary = salary_distribution(demo_analysis)
    duplication = duplication_comparison(demo_analysis)
    assert ownership["ownership_pct"].sum() == pytest.approx(
        100 * demo_analysis.config.roster_size
    )
    assert len(pairs) <= 10
    assert set(salary["field"]) == {"observed", "null"}
    assert duplication["observed_pct"].sum() == pytest.approx(100)
    assert len(comparison_cards(demo_analysis)) == 4


def test_lineup_detail_matches_entry_metrics(demo_analysis) -> None:
    entry_id = str(demo_analysis.observed.entries.iloc[0]["entry_id"])
    roster, diagnostics = lineup_detail(demo_analysis, entry_id)
    assert len(roster) == demo_analysis.config.roster_size
    assert roster["salary"].sum() == diagnostics["salary_used"]
    assert diagnostics["salary_remaining"] >= 0
    assert diagnostics["exact_dup_count"] >= 1


def test_lineup_detail_rejects_unknown_entry(demo_analysis) -> None:
    with pytest.raises(ValueError, match="unknown entry_id"):
        lineup_detail(demo_analysis, "not-a-real-entry")


def test_demo_samples_reload_and_report_preserves_baseline_error(demo_analysis):
    imported = contest_from_wide(wide_entries(demo_analysis))
    imported.validate_against_pool(demo_analysis.pool, demo_analysis.config)
    assert imported.lineups == demo_analysis.field.lineups
    with ZipFile(
        BytesIO(report_bundle(demo_analysis, source="Synthetic demo"))
    ) as archive:
        report = json.loads(archive.read("analysis.json"))
        assert report["baseline_error"] == demo_analysis.comparison.summary
        assert report["input_summary"]["entries"] == 50
