import json
from io import BytesIO
from zipfile import ZipFile

import pandas as pd
import pytest

from field_model import contest_from_wide
from field_model.interview import (
    controlled_bundle,
    controlled_fields,
    report_bundle,
    wide_entries,
)


def test_controlled_fields_match_marginals_but_differ_in_joint_structure():
    clustered, spread = controlled_fields()
    pd.testing.assert_series_equal(
        clustered.observed.player_ownership, spread.observed.player_ownership
    )
    assert set(clustered.observed.player_ownership) == {0.5}
    assert clustered.observed.summary["lineup_hhi"] == pytest.approx(0.5)
    assert spread.observed.summary["lineup_hhi"] == pytest.approx(1 / 6)
    assert clustered.observed.summary["effective_lineups"] == pytest.approx(2)
    assert spread.observed.summary["effective_lineups"] == pytest.approx(6)


def test_sample_export_reimports_as_legal_lineups():
    clustered, _ = controlled_fields()
    imported = contest_from_wide(wide_entries(clustered))
    imported.validate_against_pool(clustered.pool, clustered.config)
    assert imported.lineups == clustered.field.lineups


def test_controlled_download_includes_both_fields():
    with ZipFile(BytesIO(controlled_bundle())) as archive:
        assert archive.testzip() is None
        for name in ("clustered", "spread"):
            frame = pd.read_csv(BytesIO(archive.read(f"{name}-entries.csv")))
            assert len(frame) == 12
            assert f"{name}-analysis.zip" in archive.namelist()


def test_report_is_deterministic_and_omits_entry_metadata():
    clustered, _ = controlled_fields()
    clustered.field.entries["account_id"] = "private-account-example"
    data = report_bundle(clustered, source="Synthetic demo")
    assert data == report_bundle(clustered, source="Synthetic demo")
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        payload = json.loads(archive.read("analysis.json"))
        assert payload["metrics"]["lineup_hhi"] == pytest.approx(0.5)
        assert payload["input_summary"]["entries"] == 12
        assert payload["roster_rules"]["roster_size"] == 2
        assert "contest_id" not in payload["metrics"]
        assert all(
            b"private-account-example" not in archive.read(name)
            for name in archive.namelist()
        )
