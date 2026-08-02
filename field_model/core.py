"""Core lineup generators and diagnostics for a segment-mixture DFS field model.

This module deliberately separates two jobs:

1. Generate candidate field lineups under explicit behavioral assumptions.
2. Measure lineup-level concentration and ownership decomposition.

The generators are hypotheses until fitted against observed contest lineups.
They should not be interpreted as evidence that a segment behaves this way.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Literal, TypeAlias

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix

Lineup: TypeAlias = frozenset[str]

REQUIRED_POOL_COLUMNS = {
    "player_id",
    "player",
    "team",
    "pos",
    "salary",
    "true_mean",
    "consensus",
    "fame",
    "recency",
}


@dataclass(frozen=True)
class SlateConfig:
    """Roster and salary rules for one contest."""

    roster_size: int = 8
    salary_cap: int = 50_000
    position_min: dict[str, int] = field(
        default_factory=lambda: {"GK": 1, "D": 2, "M": 2, "F": 2}
    )
    flex_positions: tuple[str, ...] = ("D", "M", "F")
    max_per_team: int = 4
    min_salary_spend: int = 0

    @property
    def n_flex(self) -> int:
        return self.roster_size - sum(self.position_min.values())

    def validate(self) -> None:
        if self.roster_size <= 0:
            raise ValueError("roster_size must be positive")
        if self.salary_cap <= 0:
            raise ValueError("salary_cap must be positive")
        if self.min_salary_spend < 0 or self.min_salary_spend > self.salary_cap:
            raise ValueError("min_salary_spend must be between 0 and salary_cap")
        if not self.position_min:
            raise ValueError("position_min cannot be empty")
        if any(value < 0 for value in self.position_min.values()):
            raise ValueError("position minimums cannot be negative")
        if self.n_flex < 0:
            raise ValueError("position minimums exceed roster_size")
        if self.n_flex and not self.flex_positions:
            raise ValueError("flex_positions cannot be empty when flex slots exist")
        if self.max_per_team <= 0:
            raise ValueError("max_per_team must be positive")


@dataclass(frozen=True)
class SharedMenuConfig:
    """Illustrative assumptions for a shared-menu lineup generator.

    Defaults are synthetic demonstration values, not calibrated or operational
    recommendations.
    """

    menu_size: int = 25
    projection_noise_sd: float = 0.35
    choice_temperature: float = 0.45

    def validate(self) -> None:
        if self.menu_size <= 0:
            raise ValueError("menu_size must be positive")
        if self.projection_noise_sd < 0:
            raise ValueError("projection_noise_sd cannot be negative")
        if self.choice_temperature <= 0:
            raise ValueError("choice_temperature must be positive")


@dataclass(frozen=True)
class WeightedChoiceConfig:
    """Illustrative assumptions for a weighted legal-lineup random walk.

    Defaults are synthetic demonstration values, not calibrated or operational
    recommendations.
    """

    fame_weight: float = 0.45
    recency_weight: float = 0.35
    salary_weight: float = 0.20
    random_walk_steps: int = 20
    proposals_per_step: int = 12

    def validate(self) -> None:
        weights = (self.fame_weight, self.recency_weight, self.salary_weight)
        if any(value < 0 for value in weights) or sum(weights) <= 0:
            raise ValueError(
                "weighted-choice weights must be nonnegative and sum above zero"
            )
        if self.random_walk_steps <= 0:
            raise ValueError("random_walk_steps must be positive")
        if self.proposals_per_step <= 0:
            raise ValueError("proposals_per_step must be positive")


def validate_pool(pool: pd.DataFrame, cfg: SlateConfig | None = None) -> None:
    """Validate the stable-ID player-pool contract and optional slate feasibility."""

    missing = sorted(REQUIRED_POOL_COLUMNS - set(pool.columns))
    if missing:
        raise ValueError(f"player pool is missing required columns: {missing}")
    if pool.empty:
        raise ValueError("player pool cannot be empty")
    if pool["player_id"].isna().any() or pool["player_id"].astype(str).eq("").any():
        raise ValueError("player_id values must be nonempty")
    if pool["player_id"].astype(str).duplicated().any():
        raise ValueError("player_id values must be unique")
    if pool[["team", "pos"]].isna().any().any():
        raise ValueError("team and pos values cannot be missing")

    numeric = ["salary", "true_mean", "consensus", "fame", "recency"]
    converted = pool[numeric].apply(pd.to_numeric, errors="coerce")
    if converted.isna().any().any() or not np.isfinite(converted.to_numpy()).all():
        raise ValueError(f"columns {numeric} must contain finite numeric values")
    if (converted["salary"] <= 0).any():
        raise ValueError("salary values must be positive")

    if cfg is None:
        return
    cfg.validate()
    counts = pool["pos"].astype(str).value_counts()
    for pos, minimum in cfg.position_min.items():
        if int(counts.get(pos, 0)) < minimum:
            raise ValueError(f"not enough {pos} players for minimum of {minimum}")
    eligible_flex = pool["pos"].astype(str).isin(cfg.flex_positions).sum()
    required_flex_eligible = (
        sum(cfg.position_min.get(pos, 0) for pos in cfg.flex_positions) + cfg.n_flex
    )
    if eligible_flex < required_flex_eligible:
        raise ValueError("not enough flex-eligible players")
    if len(pool) < cfg.roster_size:
        raise ValueError("player pool is smaller than roster_size")


def synthetic_pool(n_teams: int = 12, seed: int = 7) -> pd.DataFrame:
    """Build a reproducible synthetic soccer-style slate for demonstrations."""

    if n_teams < 2:
        raise ValueError("n_teams must be at least 2")
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []

    for team_number in range(n_teams):
        team = f"T{team_number:02d}"
        team_strength = rng.normal(0, 1)
        for pos, count in (("GK", 1), ("D", 4), ("M", 4), ("F", 3)):
            for player_number in range(count):
                base = {"GK": 6.0, "D": 6.5, "M": 8.0, "F": 8.5}[pos]
                skill = rng.normal(0, 1)
                true_mean = max(1.0, base + 1.6 * skill + 0.9 * team_strength)
                salary = int(
                    np.clip(
                        2_500 + 620 * true_mean + rng.normal(0, 700),
                        2_500,
                        12_500,
                    )
                )
                fame = float(np.clip(rng.normal(0.5, 0.25), 0.01, 1.0))
                recency = max(0.0, true_mean + rng.normal(0, 5.5))
                consensus = (
                    true_mean
                    + 0.28 * (recency - true_mean)
                    + 1.5 * (fame - 0.5)
                    + rng.normal(0, 0.5)
                )
                player_id = f"{team}-{pos}{player_number}"
                rows.append(
                    {
                        "player_id": player_id,
                        "player": player_id,
                        "team": team,
                        "pos": pos,
                        "salary": salary,
                        "true_mean": round(true_mean, 2),
                        "consensus": round(max(0.5, consensus), 2),
                        "fame": round(fame, 3),
                        "recency": round(recency, 2),
                    }
                )
    return pd.DataFrame(rows)


def _objective_values(
    pool: pd.DataFrame, objective: str | Sequence[float] | pd.Series
) -> np.ndarray:
    if isinstance(objective, str):
        if objective not in pool:
            raise ValueError(f"objective column {objective!r} does not exist")
        values = pd.to_numeric(pool[objective], errors="coerce").to_numpy(dtype=float)
    elif isinstance(objective, pd.Series):
        values = pd.to_numeric(objective.reindex(pool.index), errors="coerce").to_numpy(
            dtype=float
        )
    else:
        values = np.asarray(objective, dtype=float)
    if values.shape != (len(pool),):
        raise ValueError("objective must have exactly one value per pool row")
    if not np.isfinite(values).all():
        raise ValueError("objective values must be finite")
    return values


def optimize(
    pool: pd.DataFrame,
    objective: str | Sequence[float] | pd.Series,
    cfg: SlateConfig,
    banned: Collection[Lineup] | None = None,
) -> Lineup | None:
    """Find the maximum-objective legal lineup using SciPy/HiGHS MILP."""

    validate_pool(pool, cfg)
    values = _objective_values(pool, objective)
    ids = pool["player_id"].astype(str).to_numpy()
    positions = pool["pos"].astype(str).to_numpy()
    teams = pool["team"].astype(str).to_numpy()
    salaries = pd.to_numeric(pool["salary"]).to_numpy(dtype=float)
    id_to_row = {player_id: row for row, player_id in enumerate(ids)}

    rows: list[np.ndarray] = []
    lower: list[float] = []
    upper: list[float] = []

    rows.append(np.ones(len(pool)))
    lower.append(float(cfg.roster_size))
    upper.append(float(cfg.roster_size))

    rows.append(salaries)
    lower.append(float(cfg.min_salary_spend))
    upper.append(float(cfg.salary_cap))

    for pos, minimum in cfg.position_min.items():
        member_row = (positions == pos).astype(float)
        maximum = minimum + (cfg.n_flex if pos in cfg.flex_positions else 0)
        rows.append(member_row)
        lower.append(float(minimum))
        upper.append(float(maximum))

    for team in pd.unique(teams):
        rows.append((teams == team).astype(float))
        lower.append(0.0)
        upper.append(float(cfg.max_per_team))

    for lineup in banned or ():
        unknown = set(lineup) - set(id_to_row)
        if unknown:
            raise ValueError(
                f"banned lineup contains unknown player IDs: {sorted(unknown)}"
            )
        ban_row = np.zeros(len(pool))
        ban_row[[id_to_row[player_id] for player_id in lineup]] = 1.0
        rows.append(ban_row)
        lower.append(0.0)
        upper.append(float(cfg.roster_size - 1))

    constraints = LinearConstraint(
        csr_matrix(np.vstack(rows)),
        np.asarray(lower),
        np.asarray(upper),
    )
    result = milp(
        c=-values,
        integrality=np.ones(len(pool)),
        bounds=Bounds(np.zeros(len(pool)), np.ones(len(pool))),
        constraints=constraints,
        options={"disp": False},
    )
    if not result.success or result.x is None:
        return None
    selected = ids[result.x > 0.5]
    if len(selected) != cfg.roster_size:
        raise RuntimeError("solver returned a lineup with the wrong roster size")
    return frozenset(selected.tolist())


def top_n_lineups(
    pool: pd.DataFrame,
    objective: str | Sequence[float] | pd.Series,
    cfg: SlateConfig,
    n: int,
) -> list[Lineup]:
    """Enumerate the best distinct legal lineups under one objective."""

    if n <= 0:
        raise ValueError("n must be positive")
    found: list[Lineup] = []
    banned: set[Lineup] = set()
    for _ in range(n):
        lineup = optimize(pool, objective, cfg, banned)
        if lineup is None:
            break
        found.append(lineup)
        banned.add(lineup)
    return found


def is_legal_lineup(lineup: Lineup, pool: pd.DataFrame, cfg: SlateConfig) -> bool:
    """Return whether a stable-ID lineup satisfies every slate constraint."""

    return legal_lineup_mask([lineup], pool, cfg)[0]


def legal_lineup_mask(
    lineups: Iterable[Lineup], pool: pd.DataFrame, cfg: SlateConfig
) -> list[bool]:
    """Validate many lineups while preparing slate arrays only once."""

    validate_pool(pool, cfg)
    ids = pool["player_id"].astype(str).to_numpy()
    id_to_row = {player_id: row for row, player_id in enumerate(ids)}
    known = set(id_to_row)
    positions = pool["pos"].astype(str).to_numpy()
    salaries = pool["salary"].to_numpy(dtype=float)
    teams = pool["team"].astype(str).to_numpy()
    result: list[bool] = []
    for lineup in lineups:
        if len(lineup) != cfg.roster_size or not set(lineup) <= known:
            result.append(False)
            continue
        rows = {id_to_row[player_id] for player_id in lineup}
        result.append(_is_legal_rows(rows, positions, salaries, teams, cfg))
    return result


def near_optimal_lineups(
    pool: pd.DataFrame,
    objective: str | Sequence[float] | pd.Series,
    cfg: SlateConfig,
    n: int,
) -> list[Lineup]:
    """Build a fast near-optimal menu with best-first legal swap search.

    Only the first lineup requires a MILP solve. The remaining menu is explored
    through legal one-player swaps and is therefore approximate, not guaranteed
    to equal the mathematical top-N ordering returned by :func:`top_n_lineups`.
    """

    if n <= 0:
        raise ValueError("n must be positive")
    validate_pool(pool, cfg)
    values = _objective_values(pool, objective)
    ids = pool["player_id"].astype(str).to_numpy()
    id_to_row = {player_id: row for row, player_id in enumerate(ids)}
    positions = pool["pos"].astype(str).to_numpy()
    salaries = pool["salary"].to_numpy(dtype=float)
    teams = pool["team"].astype(str).to_numpy()

    first = optimize(pool, values, cfg)
    if first is None:
        return []

    def score(lineup: Lineup) -> float:
        return float(sum(values[id_to_row[player_id]] for player_id in lineup))

    heap: list[tuple[float, tuple[str, ...], Lineup]] = []
    first_key = tuple(sorted(first))
    heapq.heappush(heap, (-score(first), first_key, first))
    queued = {first}
    selected: list[Lineup] = []
    expanded: set[Lineup] = set()
    all_rows = set(range(len(pool)))

    while heap and len(selected) < n:
        _, _, lineup = heapq.heappop(heap)
        selected.append(lineup)
        if lineup in expanded:
            continue
        expanded.add(lineup)
        picked_rows = {id_to_row[player_id] for player_id in lineup}
        for outgoing in tuple(picked_rows):
            for incoming in all_rows - picked_rows:
                proposed_rows = (picked_rows - {outgoing}) | {incoming}
                if not _is_legal_rows(proposed_rows, positions, salaries, teams, cfg):
                    continue
                proposed = frozenset(ids[list(proposed_rows)].tolist())
                if proposed in queued:
                    continue
                queued.add(proposed)
                key = tuple(sorted(proposed))
                heapq.heappush(heap, (-score(proposed), key, proposed))
    return sorted(selected, key=score, reverse=True)


def _softmax(values: np.ndarray, temperature: float) -> np.ndarray:
    centered = (values - np.max(values)) / temperature
    weights = np.exp(np.clip(centered, -700, 0))
    return weights / weights.sum()


def generate_shared_menu(
    pool: pd.DataFrame,
    cfg: SlateConfig,
    n_entries: int,
    behavior: SharedMenuConfig | None = None,
    seed: int = 0,
    menu: Sequence[Lineup] | None = None,
) -> list[Lineup]:
    """Generate a shared-consensus segment from a common optimized menu.

    The menu and softmax choice rule explicitly impose a behavioral hypothesis.
    Their parameters must be estimated from observed lineup frequencies.
    """

    behavior = behavior or SharedMenuConfig()
    behavior.validate()
    validate_pool(pool, cfg)
    if n_entries < 0:
        raise ValueError("n_entries cannot be negative")
    if n_entries == 0:
        return []

    rng = np.random.default_rng(seed)
    consensus = pool["consensus"].to_numpy(dtype=float)
    player_ids = pool["player_id"].astype(str).tolist()
    id_to_row = {player_id: row for row, player_id in enumerate(player_ids)}
    menu = list(menu) if menu is not None else build_shared_menu(pool, cfg, behavior)
    if not menu:
        raise ValueError("slate has no feasible shared-menu lineup")
    _validate_entries(menu, pool)
    if any(len(lineup) != cfg.roster_size for lineup in menu):
        raise ValueError("every shared-menu lineup must match roster_size")

    menu_rows = [
        np.fromiter((id_to_row[player_id] for player_id in lineup), dtype=int)
        for lineup in menu
    ]
    entries: list[Lineup] = []
    for _ in range(n_entries):
        jittered = consensus + rng.normal(
            0, behavior.projection_noise_sd, size=len(pool)
        )
        utilities = np.asarray([jittered[rows].sum() for rows in menu_rows])
        probabilities = _softmax(utilities, behavior.choice_temperature)
        entries.append(menu[int(rng.choice(len(menu), p=probabilities))])
    return entries


def build_shared_menu(
    pool: pd.DataFrame,
    cfg: SlateConfig,
    behavior: SharedMenuConfig | None = None,
    strategy: Literal["local", "exact"] = "local",
) -> list[Lineup]:
    """Build an optimized menu once for reuse during calibration.

    ``local`` uses one MILP plus a fast legal-swap search. ``exact`` repeatedly
    solves the MILP and guarantees the true top-N objective ordering.
    """

    behavior = behavior or SharedMenuConfig()
    behavior.validate()
    validate_pool(pool, cfg)
    if strategy == "local":
        return near_optimal_lineups(pool, "consensus", cfg, behavior.menu_size)
    if strategy == "exact":
        return top_n_lineups(pool, "consensus", cfg, behavior.menu_size)
    raise ValueError("strategy must be 'local' or 'exact'")


def _scaled(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values).to_numpy(dtype=float)
    low, high = float(np.min(numeric)), float(np.max(numeric))
    if high <= low:
        return np.ones(len(numeric))
    return (numeric - low) / (high - low)


def generate_weighted_choice(
    pool: pd.DataFrame,
    cfg: SlateConfig,
    n_entries: int,
    behavior: WeightedChoiceConfig | None = None,
    seed: int = 1,
) -> list[Lineup]:
    """Generate weighted random legal lineups from a constraint-safe random walk.

    Each entry begins at a legal low-salary lineup. Random player swaps are then
    proposed using fame, recency, and salary weights, and accepted only when the
    resulting lineup remains legal. The optimizer establishes feasibility; it
    does not optimize the behavioral utility used by the random walk. Walk length
    is a fitted mixing parameter, not a claim about literal user behavior.
    """

    behavior = behavior or WeightedChoiceConfig()
    behavior.validate()
    validate_pool(pool, cfg)
    if n_entries < 0:
        raise ValueError("n_entries cannot be negative")
    if n_entries == 0:
        return []

    fame = _scaled(pool["fame"])
    recency = _scaled(pool["recency"])
    salary = _scaled(pool["salary"])
    weights = (
        behavior.fame_weight * fame
        + behavior.recency_weight * recency
        + behavior.salary_weight * salary
    )
    return generate_weighted_lineups(
        pool,
        cfg,
        weights,
        n_entries,
        seed=seed,
        random_walk_steps=behavior.random_walk_steps,
        proposals_per_step=behavior.proposals_per_step,
    )


def generate_weighted_lineups(
    pool: pd.DataFrame,
    cfg: SlateConfig,
    weights: Sequence[float] | pd.Series,
    n_entries: int,
    seed: int = 1,
    random_walk_steps: int = 20,
    proposals_per_step: int = 12,
) -> list[Lineup]:
    """Generate legal lineups from explicit positive player proposal weights.

    This is a constraint-aware null sampler, not an exact maximum-entropy
    sampler. Its realized marginals must always be reported beside its target.
    """

    validate_pool(pool, cfg)
    if n_entries < 0:
        raise ValueError("n_entries cannot be negative")
    if n_entries == 0:
        return []
    if random_walk_steps <= 0 or proposals_per_step <= 0:
        raise ValueError("random-walk parameters must be positive")
    if isinstance(weights, pd.Series):
        player_ids_index = pd.Index(pool["player_id"].astype(str))
        if set(player_ids_index) <= set(weights.index.astype(str)):
            normalized_weights = weights.copy()
            normalized_weights.index = normalized_weights.index.astype(str)
            weight_values = normalized_weights.reindex(player_ids_index).to_numpy(
                dtype=float
            )
        else:
            weight_values = weights.reindex(pool.index).to_numpy(dtype=float)
    else:
        weight_values = np.asarray(weights, dtype=float)
    if weight_values.shape != (len(pool),):
        raise ValueError("weights must have exactly one value per pool row")
    if not np.isfinite(weight_values).all() or (weight_values < 0).any():
        raise ValueError("weights must be finite and nonnegative")
    if not (weight_values > 0).any():
        raise ValueError("at least one weight must be positive")
    weight_values = np.clip(weight_values, 1e-9, None)

    rng = np.random.default_rng(seed)
    positions = pool["pos"].astype(str).to_numpy()
    player_ids = pool["player_id"].astype(str).to_numpy()
    salaries = pool["salary"].to_numpy(dtype=float)
    teams = pool["team"].astype(str).to_numpy()
    anchors = _anchor_lineups(pool, cfg, salaries)
    if not anchors:
        raise ValueError("slate has no feasible weighted-choice lineup")
    id_to_row = {player_id: row for row, player_id in enumerate(player_ids.tolist())}
    anchor_rows = [{id_to_row[player_id] for player_id in anchor} for anchor in anchors]
    rows_by_position = {
        pos: np.flatnonzero(positions == pos) for pos in pd.unique(positions)
    }

    entries: list[Lineup] = []
    for _ in range(n_entries):
        picked = set(anchor_rows[int(rng.integers(len(anchor_rows)))])
        for _ in range(random_walk_steps):
            for _ in range(proposals_per_step):
                outgoing = int(rng.choice(list(picked)))
                same_position = rows_by_position[positions[outgoing]]
                available = same_position[~np.isin(same_position, list(picked))]
                if not len(available):
                    break
                probabilities = (
                    weight_values[available] / weight_values[available].sum()
                )
                incoming = int(rng.choice(available, p=probabilities))
                proposed = (picked - {outgoing}) | {incoming}
                if _is_legal_rows(proposed, positions, salaries, teams, cfg):
                    picked = proposed
                    break
        entries.append(frozenset(player_ids[list(picked)].tolist()))
    return entries


def _anchor_lineups(
    pool: pd.DataFrame, cfg: SlateConfig, salaries: np.ndarray
) -> list[Lineup]:
    """Find a cheap legal anchor for each feasible flex-position allocation."""

    if cfg.n_flex == 0:
        anchor = optimize(pool, -salaries, cfg)
        return [anchor] if anchor is not None else []

    anchors: list[Lineup] = []
    flex_positions = tuple(dict.fromkeys(cfg.flex_positions))
    for allocation in product(range(cfg.n_flex + 1), repeat=len(flex_positions)):
        if sum(allocation) != cfg.n_flex:
            continue
        exact_minimums = dict(cfg.position_min)
        for pos, extra in zip(flex_positions, allocation, strict=True):
            exact_minimums[pos] = exact_minimums.get(pos, 0) + extra
        exact_cfg = SlateConfig(
            roster_size=cfg.roster_size,
            salary_cap=cfg.salary_cap,
            position_min=exact_minimums,
            flex_positions=(),
            max_per_team=cfg.max_per_team,
            min_salary_spend=cfg.min_salary_spend,
        )
        anchor = optimize(pool, -salaries, exact_cfg)
        if anchor is not None:
            anchors.append(anchor)
    return list(dict.fromkeys(anchors))


def _is_legal_rows(
    picked: set[int],
    positions: np.ndarray,
    salaries: np.ndarray,
    teams: np.ndarray,
    cfg: SlateConfig,
) -> bool:
    if len(picked) != cfg.roster_size:
        return False
    rows = list(picked)
    salary_total = float(salaries[rows].sum())
    if not cfg.min_salary_spend <= salary_total <= cfg.salary_cap:
        return False
    _, team_counts = np.unique(teams[rows], return_counts=True)
    if int(team_counts.max()) > cfg.max_per_team:
        return False
    selected_positions, raw_counts = np.unique(positions[rows], return_counts=True)
    position_counts = dict(
        zip(selected_positions.tolist(), raw_counts.tolist(), strict=True)
    )
    for pos, minimum in cfg.position_min.items():
        count = int(position_counts.get(pos, 0))
        maximum = minimum + (cfg.n_flex if pos in cfg.flex_positions else 0)
        if not minimum <= count <= maximum:
            return False
    allowed_positions = set(cfg.position_min) | set(cfg.flex_positions)
    return set(selected_positions) <= allowed_positions


def _validate_entries(entries: Iterable[Lineup], pool: pd.DataFrame) -> list[Lineup]:
    materialized = list(entries)
    known = set(pool["player_id"].astype(str))
    unknown = set().union(*(set(lineup) for lineup in materialized)) - known
    if unknown:
        raise ValueError(f"entries contain unknown player IDs: {sorted(unknown)}")
    return materialized


def ownership(entries: Iterable[Lineup], pool: pd.DataFrame) -> pd.Series:
    """Return marginal ownership indexed by stable player ID."""

    validate_pool(pool)
    materialized = _validate_entries(entries, pool)
    player_ids = pool["player_id"].astype(str)
    counts = pd.Series(0.0, index=player_ids, name="ownership")
    for lineup in materialized:
        for player_id in lineup:
            counts.loc[player_id] += 1
    if materialized:
        counts /= len(materialized)
    return counts


def lineup_hhi(entries: Iterable[Lineup]) -> float:
    """Herfindahl concentration over exact lineup frequencies."""

    materialized = list(entries)
    if not materialized:
        return float("nan")
    shares = np.asarray(list(Counter(materialized).values()), dtype=float)
    shares /= len(materialized)
    return float(np.square(shares).sum())


def effective_lineups(entries: Iterable[Lineup]) -> float:
    """Return the inverse-HHI effective number of equally common lineups."""

    hhi = lineup_hhi(entries)
    return float(1.0 / hhi) if np.isfinite(hhi) and hhi > 0 else float("nan")


def mean_jaccard(
    entries: Sequence[Lineup], sample_pairs: int = 2_000, seed: int = 3
) -> float:
    """Estimate mean pairwise entry overlap without hashing lineups."""

    if len(entries) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    total_pairs = len(entries) * (len(entries) - 1) // 2
    if total_pairs <= sample_pairs:
        pairs = combinations(range(len(entries)), 2)
    else:
        sampled: set[tuple[int, int]] = set()
        while len(sampled) < sample_pairs:
            first, second = rng.choice(len(entries), size=2, replace=False)
            sampled.add(tuple(sorted((int(first), int(second)))))
        pairs = iter(sampled)
    values = [
        len(entries[first] & entries[second]) / len(entries[first] | entries[second])
        for first, second in pairs
    ]
    return float(np.mean(values))


def centroid(entries: Iterable[Lineup], pool: pd.DataFrame) -> pd.Series:
    """Return the segment exposure vector indexed by stable player ID."""

    return ownership(entries, pool)


def centroid_distance(
    lineup: Lineup, entries: Iterable[Lineup], pool: pd.DataFrame
) -> float:
    """Return L2 distance from a lineup vector to segment marginal exposures."""

    exposure = centroid(entries, pool)
    vector = pd.Series(0.0, index=exposure.index)
    unknown = set(lineup) - set(vector.index)
    if unknown:
        raise ValueError(f"lineup contains unknown player IDs: {sorted(unknown)}")
    vector.loc[list(lineup)] = 1.0
    return float(np.linalg.norm(vector.to_numpy() - exposure.to_numpy()))


def duplication_count(lineup: Lineup, entries: Iterable[Lineup]) -> int:
    """Count field entries that exactly match a candidate lineup."""

    return Counter(entries)[lineup]


def ownership_lift(
    segment_ownership: pd.Series, aggregate_ownership: pd.Series
) -> pd.Series:
    """Return segment ownership divided by aggregate ownership.

    This is a relative exposure diagnostic, not an estimate of fade EV.
    """

    denominator = aggregate_ownership.replace(0, np.nan)
    return segment_ownership / denominator


def ownership_source_share(
    segment_ownership: pd.Series,
    aggregate_ownership: pd.Series,
    segment_weight: float,
) -> pd.Series:
    """Return the fraction of aggregate player ownership supplied by a segment."""

    if not 0 <= segment_weight <= 1:
        raise ValueError("segment_weight must be between zero and one")
    denominator = aggregate_ownership.replace(0, np.nan)
    result = segment_weight * segment_ownership / denominator
    return result.clip(lower=0, upper=1)


def segment_report(
    name: str, entries: Sequence[Lineup], pool: pd.DataFrame
) -> dict[str, object]:
    """Summarize observed or generated lineup concentration."""

    exposure = ownership(entries, pool)
    counts = Counter(entries)
    hhi = lineup_hhi(entries)
    unique = len(counts)
    return {
        "segment": name,
        "entries": len(entries),
        "unique_lineups": unique,
        "unique_pct": round(100 * unique / len(entries), 1) if entries else np.nan,
        "lineup_hhi": round(hhi, 4) if np.isfinite(hhi) else np.nan,
        "effective_lineups": (
            round(1 / hhi, 1) if np.isfinite(hhi) and hhi > 0 else np.nan
        ),
        "mean_jaccard": (
            round(mean_jaccard(entries), 3) if len(entries) >= 2 else np.nan
        ),
        "most_duplicated_lineup": max(counts.values(), default=0),
        "max_ownership_pct": (
            round(100 * float(exposure.max()), 1) if len(exposure) else np.nan
        ),
        "players_over_40_pct": int((exposure > 0.40).sum()),
    }
