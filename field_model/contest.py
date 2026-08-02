"""Canonical contest-entry ingestion for observed DFS fields."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .core import Lineup, SlateConfig, legal_lineup_mask, validate_pool

CANONICAL_METADATA = {
    "entry_id",
    "account_id",
    "score",
    "rank",
    "payout",
    "salary_used",
}


@dataclass
class ContestField:
    """Canonical observed entries with one stable-ID frozenset per row."""

    entries: pd.DataFrame
    contest_id: str | None = None

    def __post_init__(self) -> None:
        self.entries = self.entries.copy().reset_index(drop=True)
        required = {"entry_id", "lineup"}
        missing = sorted(required - set(self.entries.columns))
        if missing:
            raise ValueError(f"contest entries are missing columns: {missing}")
        self.entries["entry_id"] = self.entries["entry_id"].astype(str)
        if self.entries["entry_id"].eq("").any():
            raise ValueError("entry_id values must be nonempty")
        if self.entries["entry_id"].duplicated().any():
            raise ValueError("entry_id values must be unique")
        self.entries["lineup"] = self.entries["lineup"].map(_as_lineup)
        if self.entries.empty:
            raise ValueError("contest field cannot be empty")
        sizes = self.entries["lineup"].map(len)
        if (sizes == 0).any():
            raise ValueError("lineups cannot be empty")
        if sizes.nunique() != 1:
            raise ValueError("all lineups must have the same roster size")
        for column in ("score", "rank", "payout", "salary_used"):
            if column in self.entries:
                self.entries[column] = pd.to_numeric(
                    self.entries[column], errors="coerce"
                )

    @property
    def lineups(self) -> list[Lineup]:
        return self.entries["lineup"].tolist()

    @property
    def field_size(self) -> int:
        return len(self.entries)

    @property
    def roster_size(self) -> int:
        return len(self.entries.iloc[0]["lineup"])

    def validate_against_pool(
        self,
        pool: pd.DataFrame,
        cfg: SlateConfig | None = None,
        require_legal: bool = True,
    ) -> None:
        validate_pool(pool, cfg)
        known = set(pool["player_id"].astype(str))
        used = set().union(*(set(lineup) for lineup in self.lineups))
        unknown = sorted(used - known)
        if unknown:
            raise ValueError(
                f"contest contains {len(unknown)} unknown player IDs: {unknown[:8]}"
            )
        if cfg is not None and self.roster_size != cfg.roster_size:
            raise ValueError(
                f"contest roster size {self.roster_size} does not match "
                f"configuration {cfg.roster_size}"
            )
        if cfg is not None and require_legal:
            mask = legal_lineup_mask(self.lineups, pool, cfg)
            illegal = self.entries.loc[
                ~pd.Series(mask, index=self.entries.index), "entry_id"
            ].tolist()
            if illegal:
                raise ValueError(
                    f"contest contains {len(illegal)} illegal lineups; "
                    f"first entry IDs: {illegal[:8]}"
                )


def contest_from_wide(
    frame: pd.DataFrame,
    player_columns: Sequence[str] | None = None,
    *,
    entry_id_column: str = "entry_id",
    metadata_columns: dict[str, str] | None = None,
    contest_id: str | None = None,
) -> ContestField:
    """Convert one-row-per-entry data with player columns into canonical form."""

    if player_columns is None:
        player_columns = sorted(
            (
                column
                for column in frame.columns
                if re.fullmatch(r"player_?\d+", str(column), flags=re.I)
            ),
            key=_numeric_suffix,
        )
    player_columns = list(player_columns)
    if not player_columns:
        raise ValueError("no player columns were supplied or detected")
    required = {entry_id_column, *player_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"wide entry data are missing columns: {missing}")

    output = pd.DataFrame(
        {
            "entry_id": frame[entry_id_column].astype(str),
            "lineup": frame[player_columns].apply(
                lambda row: frozenset(_clean_player_ids(row)), axis=1
            ),
        }
    )
    for canonical, source in (metadata_columns or {}).items():
        if canonical not in CANONICAL_METADATA - {"entry_id"}:
            raise ValueError(f"unsupported metadata column: {canonical}")
        if source not in frame:
            raise ValueError(f"metadata source column does not exist: {source}")
        output[canonical] = frame[source].to_numpy()
    return ContestField(output, contest_id=contest_id)


def contest_from_long(
    frame: pd.DataFrame,
    *,
    entry_id_column: str = "entry_id",
    player_id_column: str = "player_id",
    metadata_columns: dict[str, str] | None = None,
    contest_id: str | None = None,
) -> ContestField:
    """Convert one-row-per-entry-player data into canonical contest entries."""

    required = {entry_id_column, player_id_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"long entry data are missing columns: {missing}")
    if frame[[entry_id_column, player_id_column]].isna().any().any():
        raise ValueError("entry and player IDs cannot be missing")

    grouped = frame.groupby(entry_id_column, sort=False, dropna=False)
    output = (
        grouped[player_id_column]
        .agg(lambda values: frozenset(str(value).strip() for value in values))
        .rename("lineup")
        .reset_index()
    )
    output = output.rename(columns={entry_id_column: "entry_id"})
    for canonical, source in (metadata_columns or {}).items():
        if canonical not in CANONICAL_METADATA - {"entry_id"}:
            raise ValueError(f"unsupported metadata column: {canonical}")
        if source not in frame:
            raise ValueError(f"metadata source column does not exist: {source}")
        consistency = grouped[source].nunique(dropna=False)
        if (consistency > 1).any():
            raise ValueError(f"metadata column {source!r} varies within an entry")
        values = grouped[source].first().reset_index(drop=True)
        output[canonical] = values
    return ContestField(output, contest_id=contest_id)


def contest_from_draftkings(
    frame: pd.DataFrame,
    pool: pd.DataFrame,
    roster_slots: Sequence[str],
    *,
    lineup_column: str = "Lineup",
    entry_id_column: str = "EntryId",
    metadata_columns: dict[str, str] | None = None,
    contest_id: str | None = None,
) -> ContestField:
    """Parse DraftKings-style lineup strings using the supplied player pool.

    Player names are resolved to stable IDs. Duplicate normalized player names
    are rejected because guessing between them would corrupt observed ownership.
    """

    validate_pool(pool)
    required = {lineup_column, entry_id_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"DraftKings data are missing columns: {missing}")
    if not roster_slots:
        raise ValueError("roster_slots cannot be empty")
    name_to_id = _unique_name_map(pool)
    lineups = [
        _parse_slot_lineup(text, roster_slots, name_to_id)
        for text in frame[lineup_column]
    ]
    output = pd.DataFrame(
        {"entry_id": frame[entry_id_column].astype(str), "lineup": lineups}
    )
    for canonical, source in (metadata_columns or {}).items():
        if canonical not in CANONICAL_METADATA - {"entry_id"}:
            raise ValueError(f"unsupported metadata column: {canonical}")
        if source not in frame:
            raise ValueError(f"metadata source column does not exist: {source}")
        output[canonical] = frame[source].to_numpy()
    return ContestField(output, contest_id=contest_id)


def load_wide_csv(path: str | Path, **kwargs: object) -> ContestField:
    """Read a CSV and pass it to :func:`contest_from_wide`."""

    return contest_from_wide(pd.read_csv(path), **kwargs)


def load_long_csv(path: str | Path, **kwargs: object) -> ContestField:
    """Read a CSV and pass it to :func:`contest_from_long`."""

    return contest_from_long(pd.read_csv(path), **kwargs)


def load_draftkings_csv(
    path: str | Path,
    pool: pd.DataFrame,
    roster_slots: Sequence[str],
    **kwargs: object,
) -> ContestField:
    """Read a DraftKings CSV and parse its lineup strings."""

    return contest_from_draftkings(pd.read_csv(path), pool, roster_slots, **kwargs)


def _parse_slot_lineup(
    raw: object,
    roster_slots: Sequence[str],
    name_to_id: dict[str, str],
) -> Lineup:
    text = " ".join(str(raw).split())
    resolved: list[str] = []
    for index, slot in enumerate(roster_slots):
        prefix = f"{slot} "
        if not text.upper().startswith(prefix.upper()):
            raise ValueError(
                f"expected roster slot {slot!r} in lineup fragment {text!r}"
            )
        remainder = text[len(prefix) :]
        if index == len(roster_slots) - 1:
            player_text = remainder
            text = ""
        else:
            next_slot = roster_slots[index + 1]
            candidates: list[tuple[int, str, str]] = []
            marker = re.compile(rf"\s+{re.escape(next_slot)}\s+", re.I)
            for match in marker.finditer(remainder):
                possible_name = remainder[: match.start()].strip()
                normalized = _normalize_name(possible_name)
                if normalized in name_to_id:
                    candidates.append(
                        (len(possible_name), possible_name, remainder[match.end() :])
                    )
            if not candidates:
                raise ValueError(
                    f"could not resolve player before slot {next_slot!r} "
                    f"in lineup fragment {remainder!r}"
                )
            _, player_text, after_slot = max(candidates)
            text = f"{next_slot} {after_slot}"
        normalized = _normalize_name(player_text)
        if normalized not in name_to_id:
            raise ValueError(f"unknown player name in lineup: {player_text!r}")
        resolved.append(name_to_id[normalized])
    lineup = frozenset(resolved)
    if len(lineup) != len(roster_slots):
        raise ValueError("lineup contains a duplicate player")
    return lineup


def _unique_name_map(pool: pd.DataFrame) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for player_id, player in pool[["player_id", "player"]].itertuples(
        index=False, name=None
    ):
        for alias in {str(player_id), str(player)}:
            candidates.setdefault(_normalize_name(alias), []).append(str(player_id))
    ambiguous = {name for name, ids in candidates.items() if len(set(ids)) > 1}
    return {name: ids[0] for name, ids in candidates.items() if name not in ambiguous}


def _normalize_name(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _as_lineup(value: object) -> Lineup:
    if isinstance(value, frozenset):
        return frozenset(str(player_id).strip() for player_id in value)
    if isinstance(value, (set, list, tuple)):
        return frozenset(str(player_id).strip() for player_id in value)
    raise ValueError("lineup values must be a set-like collection of player IDs")


def _clean_player_ids(values: Iterable[object]) -> list[str]:
    output: list[str] = []
    for value in values:
        if pd.isna(value) or not str(value).strip():
            raise ValueError("player columns cannot contain missing values")
        output.append(str(value).strip())
    return output


def _numeric_suffix(value: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", str(value))
    return (int(match.group(1)) if match else 10**9, str(value))
