"""Regenerate the tracked synthetic dashboard fixture."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from field_model import (
    ContestField,
    FishConfig,
    SlateConfig,
    ToutConfig,
    generate_fish,
    generate_tout,
    ownership_weighted_null,
    synthetic_pool,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "field_model" / "demo_data"


def main() -> None:
    seed = 7
    entries_per_segment = 75
    config = SlateConfig()
    pool = synthetic_pool(n_teams=8, seed=seed)
    tout = generate_tout(
        pool,
        config,
        entries_per_segment,
        behavior=ToutConfig(
            menu_size=12,
            projection_noise_sd=0.35,
            choice_temperature=0.45,
        ),
        seed=seed + 11,
    )
    fish = generate_fish(
        pool,
        config,
        entries_per_segment,
        behavior=FishConfig(random_walk_steps=15),
        seed=seed + 12,
    )
    lineups = tout + fish
    segments = ["shared-consensus hypothesis"] * len(tout) + [
        "weighted-random hypothesis"
    ] * len(fish)
    observed = ContestField(
        pd.DataFrame(
            {
                "entry_id": [f"demo-{index:04d}" for index in range(len(lineups))],
                "segment_hypothesis": segments,
                "lineup": lineups,
            }
        ),
        contest_id="synthetic-demo",
    )
    baseline = ownership_weighted_null(
        observed,
        pool,
        config,
        seed=seed + 44,
        random_walk_steps=12,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pool.to_csv(OUTPUT / "player_pool.csv", index=False)
    _entry_export(observed).to_csv(OUTPUT / "observed_entries.csv", index=False)
    _entry_export(baseline).to_csv(OUTPUT / "null_entries.csv", index=False)


def _entry_export(field: ContestField) -> pd.DataFrame:
    result = field.entries.copy()
    result["lineup"] = result["lineup"].map(
        lambda lineup: "|".join(sorted(lineup))
    )
    return result


if __name__ == "__main__":
    main()
