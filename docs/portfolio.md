# Portfolio notes

## Career signal

This project demonstrates data-contract design, mixed-integer optimization,
reproducible simulation, input validation, sparse-matrix diagnostics,
calibration checks, testable CLI design, packaging, and CI.

## Demo path

```bash
sh scripts/dev.sh setup
sh scripts/dev.sh check
```

On Windows, use `.\dev.cmd setup` and `.\dev.cmd check`. The full check runs 19 deterministic tests and produces an ignored verification receipt in addition to terminal evidence.

The demo constructs a deterministic synthetic slate, generates two neutral
field hypotheses, compares lineup concentration, and evaluates an
ownership-weighted legal null. No private data or network access is required.

## Honest limitations

- Generator settings are illustrative and unfitted.
- The null sampler is constraint-aware but not exact maximum entropy.
- The package does not model sport-specific outcome correlation, payouts,
  late swap, contest selection, or portfolio optimization.
- Empirical usefulness requires chronological validation on legally obtained
  contest exports, grouped by slate.

## Resume-ready evidence

- Built a tested Python package that validates complete DFS lineups, generates
  constraint-safe synthetic fields with SciPy/HiGHS MILP, and measures
  duplication, concentration, overlap, stacks, and co-ownership.
- Designed calibration diagnostics that report menu coverage, marginal error,
  matrix rank, and conditioning so weakly identified models are not presented
  as validated behavior.
