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

On Windows, use `.\dev.cmd setup`, `.\dev.cmd app`, and `.\dev.cmd check`.
The full check runs the current test suite and writes an ignored receipt.
See the [interview walkthrough](interview-guide.md) for the guided five-minute demo.

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

Use these as drafts only after you can explain and reproduce the work. The
project used AI coding assistance; describe your actual contributions accurately.

- Built a tested Python package that validates complete DFS lineups, generates
  constraint-safe synthetic fields with SciPy/HiGHS MILP, and measures
  duplication, concentration, overlap, stacks, and co-ownership.
- Designed calibration diagnostics that report menu coverage, marginal error,
  matrix rank, and conditioning so weakly identified models are not presented
  as validated behavior.
- Delivered a reproducible Streamlit case study demonstrating identical player
  marginals with a threefold difference in lineup concentration, with portable
  report downloads and tested CSV adapters.
