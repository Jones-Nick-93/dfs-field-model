from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = """
import json
from field_model import (
    SharedMenuConfig,
    SlateConfig,
    WeightedChoiceConfig,
    generate_shared_menu,
    generate_weighted_choice,
    synthetic_pool,
)

pool = synthetic_pool(n_teams=6, seed=7)
slate = SlateConfig()
shared = generate_shared_menu(
    pool,
    slate,
    30,
    behavior=SharedMenuConfig(menu_size=5),
    seed=11,
)
weighted = generate_weighted_choice(
    pool,
    slate,
    30,
    behavior=WeightedChoiceConfig(random_walk_steps=5, proposals_per_step=5),
    seed=12,
)
print(json.dumps([[sorted(lineup) for lineup in shared], [sorted(lineup) for lineup in weighted]]))
"""


def generated_lineups(hash_seed: str) -> str:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout


def test_seeded_generators_are_stable_across_python_processes() -> None:
    assert generated_lineups("1") == generated_lineups("987654")
