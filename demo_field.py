"""Reproducible demonstration of lineup-level segment concentration."""

from __future__ import annotations

import pandas as pd

from field_model import (
    ContestField,
    SharedMenuConfig,
    SlateConfig,
    WeightedChoiceConfig,
    centroid_distance,
    compare_field_reports,
    duplication_count,
    generate_shared_menu,
    generate_weighted_choice,
    lineup_hhi,
    observed_field_report,
    optimize,
    ownership,
    ownership_lift,
    ownership_source_share,
    ownership_weighted_null,
    segment_report,
    synthetic_pool,
)


def main() -> None:
    pd.set_option("display.width", 180)
    pd.set_option("display.max_columns", 30)

    slate = SlateConfig()
    pool = synthetic_pool(n_teams=12, seed=7)
    shared_menu_config = SharedMenuConfig(
        menu_size=25,
        projection_noise_sd=0.35,
        choice_temperature=0.45,
    )
    weighted_choice_config = WeightedChoiceConfig()

    n_shared_menu = 600
    n_weighted_choice = 600
    shared_menu_weight = 0.50
    weighted_choice_weight = 1 - shared_menu_weight

    print(
        f"slate: {len(pool)} players, roster {slate.roster_size}, "
        f"cap ${slate.salary_cap:,}, flex slots {slate.n_flex}\n"
    )
    print("Generating explicit, unfitted behavioral hypotheses...")
    shared_menu = generate_shared_menu(
        pool, slate, n_shared_menu, behavior=shared_menu_config, seed=11
    )
    weighted_choice = generate_weighted_choice(
        pool, slate, n_weighted_choice, behavior=weighted_choice_config, seed=12
    )

    report = pd.DataFrame(
        [
            segment_report("shared-menu hypothesis", shared_menu, pool),
            segment_report("weighted-choice hypothesis", weighted_choice, pool),
        ]
    )
    print("\n=== generated segment concentration ===")
    print(report.to_string(index=False))

    shared_menu_hhi = lineup_hhi(shared_menu)
    uniform_menu_hhi = 1 / len(set(shared_menu))
    print(
        f"\nShared-menu HHI {shared_menu_hhi:.4f} vs uniform over observed menu "
        f"{uniform_menu_hhi:.4f}: {shared_menu_hhi / uniform_menu_hhi:.1f}x."
    )
    print(
        "This difference is an output of explicit menu, noise, and choice "
        "parameters; it is not empirical validation."
    )

    own_shared_menu = ownership(shared_menu, pool)
    own_weighted_choice = ownership(weighted_choice, pool)
    own_aggregate = (
        shared_menu_weight * own_shared_menu
        + weighted_choice_weight * own_weighted_choice
    )

    table = pool.set_index("player_id")[
        ["player", "team", "pos", "salary", "true_mean", "consensus"]
    ].copy()
    table["own_aggregate_pct"] = (100 * own_aggregate).round(1)
    table["own_shared_menu_pct"] = (100 * own_shared_menu).round(1)
    table["own_weighted_choice_pct"] = (100 * own_weighted_choice).round(1)
    table["shared_menu_lift"] = ownership_lift(own_shared_menu, own_aggregate).round(2)
    table["shared_menu_source_share"] = ownership_source_share(
        own_shared_menu, own_aggregate, shared_menu_weight
    ).round(2)
    table["projection_error"] = (table["consensus"] - table["true_mean"]).round(2)

    live = table.loc[table["own_aggregate_pct"] > 4].sort_values(
        "own_aggregate_pct", ascending=False
    )
    print("\n=== most-owned players, decomposed by source ===")
    print(live.head(14).to_string())

    pair = _matched_ownership_pair(live)
    if pair is not None:
        high, low = pair
        print("\n=== matched aggregate ownership, different source ===")
        for label, row in (
            ("shared-menu-heavy", high),
            ("weighted-choice-heavy", low),
        ):
            print(
                f"{label:<10} {row.name:<10} aggregate "
                f"{row['own_aggregate_pct']:>5.1f}% | shared-menu "
                f"{row['own_shared_menu_pct']:>5.1f}% | weighted-choice "
                f"{row['own_weighted_choice_pct']:>5.1f}% | shared-menu source "
                f"{row['shared_menu_source_share']:.2f}"
            )
        print(
            "The decomposition distinguishes the players; an outcome-aware "
            "contest simulation is still required to turn it into fade EV."
        )

    print("\n=== candidate lineup diagnostics ===")
    for label, objective in (
        ("consensus-optimal", "consensus"),
        ("model-optimal", "true_mean"),
    ):
        lineup = optimize(pool, objective, slate)
        if lineup is None:
            continue
        true_points = pool.set_index("player_id").loc[list(lineup), "true_mean"].sum()
        print(
            f"{label:<18} shared_menu_dups="
            f"{duplication_count(lineup, shared_menu):>4} "
            f"weighted_choice_dups={duplication_count(lineup, weighted_choice):>3} "
            f"shared_menu_distance="
            f"{centroid_distance(lineup, shared_menu, pool):.3f} "
            f"synthetic_true_mean={true_points:.1f}"
        )

    print(
        "\nInterpret these as diagnostics from a synthetic hypothesis, "
        "not production EV estimates."
    )

    combined_lineups = shared_menu + weighted_choice
    observed_hypothesis = ContestField(
        pd.DataFrame(
            {
                "entry_id": [
                    f"synthetic-{index:04d}" for index in range(len(combined_lineups))
                ],
                "lineup": combined_lineups,
            }
        ),
        contest_id="synthetic-mixture",
    )
    null_field = ownership_weighted_null(
        observed_hypothesis,
        pool,
        slate,
        seed=44,
        random_walk_steps=15,
    )
    observed_report = observed_field_report(observed_hypothesis, pool, slate)
    null_report = observed_field_report(null_field, pool, slate)
    comparison = compare_field_reports(observed_report, null_report)
    print("\n=== ownership-only legal null comparison ===")
    for metric, value in comparison.summary.items():
        print(f"{metric:<32} {value:.5f}")
    print(
        "The null comparison asks whether marginals alone reproduce joint "
        "lineup structure. Its marginal error is reported rather than hidden."
    )


def _matched_ownership_pair(
    table: pd.DataFrame, tolerance_pct: float = 1.5
) -> tuple[pd.Series, pd.Series] | None:
    best: tuple[float, pd.Series, pd.Series] | None = None
    candidates = table.dropna(subset=["shared_menu_source_share"])
    for first in range(len(candidates)):
        for second in range(first + 1, len(candidates)):
            left, right = candidates.iloc[first], candidates.iloc[second]
            if (
                abs(left["own_aggregate_pct"] - right["own_aggregate_pct"])
                > tolerance_pct
            ):
                continue
            spread = abs(
                left["shared_menu_source_share"] - right["shared_menu_source_share"]
            )
            if best is None or spread > best[0]:
                best = (spread, left, right)
    if best is None:
        return None
    _, left, right = best
    return (
        (left, right)
        if left["shared_menu_source_share"] > right["shared_menu_source_share"]
        else (right, left)
    )


if __name__ == "__main__":
    main()
