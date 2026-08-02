from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from field_model import SlateConfig, generate_weighted_choice, synthetic_pool


def test_analyze_field_cli_writes_auditable_outputs(tmp_path: Path) -> None:
    pool = synthetic_pool(n_teams=6, seed=51)
    cfg = SlateConfig()
    lineups = generate_weighted_choice(pool, cfg, 8, seed=52)
    pool_path = tmp_path / "pool.csv"
    entries_path = tmp_path / "entries.csv"
    output_path = tmp_path / "report"
    pool.to_csv(pool_path, index=False)
    rows = []
    for index, lineup in enumerate(lineups):
        row = {"entry_id": f"e-{index}", "score": 100 + index}
        row.update(
            {
                f"player_{slot + 1}": player_id
                for slot, player_id in enumerate(sorted(lineup))
            }
        )
        rows.append(row)
    pd.DataFrame(rows).to_csv(entries_path, index=False)

    script = Path(__file__).parents[1] / "analyze_field.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--pool",
            str(pool_path),
            "--entries",
            str(entries_path),
            "--metadata",
            "score=score",
            "--roster-size",
            "8",
            "--salary-cap",
            "50000",
            "--position-min",
            "GK=1,D=2,M=2,F=2",
            "--flex-positions",
            "D,M,F",
            "--max-per-team",
            "4",
            "--output-dir",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads((output_path / "observed_summary.json").read_text())
    assert summary["entries"] == 8
    assert summary["winning_score"] == 107
    assert (output_path / "observed_pair_ownership.csv").exists()
    assert "Wrote diagnostics" in result.stdout
