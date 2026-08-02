# Contest ingestion

The analysis boundary is a canonical table with one row per entry:

```text
entry_id | lineup | account_id? | score? | rank? | payout? | salary_used?
```

`lineup` is represented internally as a set of stable player IDs. Every import
is checked for duplicate entry IDs, uniform roster size, unknown players, salary
violations, position violations, and team-limit violations before metrics are
calculated.

## Wide CSV

Player columns named `player1`, `player2`, or `player_1`, `player_2`, and so on
are detected automatically:

```powershell
python analyze_field.py `
  --pool data/player_pool.csv `
  --entries data/contest.csv `
  --format wide `
  --entry-id-column entry_id `
  --metadata account_id=username `
  --metadata score=points `
  --roster-size 8 `
  --salary-cap 50000 `
  --position-min GK=1,D=2,M=2,F=2 `
  --flex-positions D,M,F `
  --max-per-team 4 `
  --with-null
```

Use `--player-columns GK,D1,D2,M1,M2,F1,F2,UTIL` when columns do not follow the
automatic naming convention.

## Long CSV

For one row per entry-player combination:

```powershell
python analyze_field.py `
  --pool data/player_pool.csv `
  --entries data/entry_players.csv `
  --format long `
  --entry-id-column entry_id `
  --player-id-column player_id `
  --roster-size 8 `
  --salary-cap 50000 `
  --position-min GK=1,D=2,M=2,F=2 `
  --flex-positions D,M,F `
  --max-per-team 4
```

## DraftKings lineup strings

DraftKings names are resolved through the supplied player pool and converted to
stable IDs. Ambiguous duplicate names fail rather than being guessed:

```powershell
python analyze_field.py `
  --pool data/player_pool.csv `
  --entries data/dk_contest.csv `
  --format draftkings `
  --entry-id-column EntryId `
  --lineup-column Lineup `
  --roster-slots GK,D,D,M,M,F,F,UTIL `
  --metadata account_id=EntryName `
  --metadata score=Points `
  --metadata rank=Rank `
  --roster-size 8 `
  --salary-cap 50000 `
  --position-min GK=1,D=2,M=2,F=2 `
  --flex-positions D,M,F `
  --max-per-team 4 `
  --with-null
```

## Outputs

The command writes:

- Summary JSON
- Validated entry-level salary and duplication data
- Marginal player ownership
- Player-pair ownership, independent expectation, excess, and lift
- Exact-duplication distribution
- Team-stack and position-shape distributions
- Optional ownership-weighted null-field diagnostics and errors

The null sampler uses observed ownership only as proposal weights. It does not
force a perfect marginal match, so ownership error is always reported alongside
joint-structure error. This prevents a poorly matched null from being mistaken
for evidence of segmentation.
