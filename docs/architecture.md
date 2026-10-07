# Architecture

## Data flow

```text
player pool + roster rules
          |
          v
canonical contest field <---- wide / long / provider-style adapters
          |
          +---- observed diagnostics
          |       ownership, pairs, stacks, duplication, salary
          |
          +---- ownership-weighted legal null
          |       realized marginal and joint-structure errors
          |
          +---- calibration
                  mixture weights, menu coverage, choice parameters
          |
          +---- dashboard transforms ----> Streamlit presentation
```

## Module boundaries

### `core.py`

Owns roster feasibility, MILP construction, fast menu search, lineup generators,
and low-level concentration metrics. Lineups are immutable sets of stable player
IDs; positional DataFrame indices never cross this boundary.

### `contest.py`

Normalizes external entry formats into `ContestField`. Validation occurs before
analysis so downstream functions can assume uniform roster size and known IDs.
Provider-specific string parsing resolves player names through the supplied pool
and rejects ambiguous matches.

### `diagnostics.py`

Calculates quantities directly identifiable from complete lineups: exact
frequency, HHI, overlap, salary remaining, stack structure, position shape, and
pair co-ownership. It contains no latent behavioral labeling.

### `baselines.py`

Builds a legal lineup null using observed ownership as proposal weights. This is
not presented as an exact maximum-entropy sampler; realized ownership error is
part of every comparison.

### `calibration.py`

Contains deliberately limited fitting tools. Mixture weights are constrained to
the simplex and accompanied by rank diagnostics. Shared-menu fitting measures
exact menu coverage before tuning the conditional choice process.

### `dashboard.py` and `app.py`

`dashboard.py` turns analytical reports into display-ready tables without
importing Streamlit. `app.py` owns widgets, caching, charts, layout, and upload
orchestration. This boundary keeps calculations testable without a browser and
prevents UI code from becoming a second analytical implementation.

### `interview.py`

Builds the exact-marginal controlled case with the same legality and diagnostic
functions used for larger fields. Exports deterministic aggregate report ZIPs
and sample wide CSVs. Account metadata and individual entry rosters are excluded
from reports, while aggregate player labels remain explicit.

## Important invariants

- `player_id` is unique and nonempty.
- Every lineup has exactly `roster_size` distinct players.
- Every reported contest lineup is legal under one explicit `SlateConfig`.
- Randomized public functions accept a seed.
- Generated concentration is never described as empirical validation.

## Scaling considerations

- Bulk legality validation prepares slate arrays once for the entire field.
- Player-pair calculations use a sparse entry-player matrix.
- Near-optimal menus avoid repeated MILP solves when exact ordering is not
  required.
- Deterministic menus can be cached by slate and projection snapshot during
  calibration.

## Deferred layers

The package does not yet implement sport-specific correlated outcomes, payout
simulation, late swap, or portfolio optimization. Those belong after observed
field structure is validated on chronological holdouts.
