# Codex project context

Last reviewed: 2026-10-06
Repository class: public and sanitized
Runtime: local research package and GitHub CI

## Purpose and milestone

This package models a DFS contest field as a distribution over complete lineups and provides validated ingestion, diagnostics, synthetic generators, null models, and calibration utilities. The current milestone is chronological validation on legally obtained lineup-level exports without publishing those exports or private fitted parameters.

It is not a wagering product and does not claim production expected-value estimates.

## System map

```text
synthetic or private contest input
    -> schema and lineup validation
    -> canonical contest representation
    -> field/null-model diagnostics
    -> calibration summaries
    -> JSON/CSV report, reproducible demo, or Streamlit dashboard
```

Private inputs may be used locally but must never be committed or included in public outputs.

## Important paths

| Path | Purpose | Public-safe? |
|---|---|---|
| `field_model/` | Core roster, contest, diagnostic, baseline, and calibration logic | Yes |
| `tests/` | Deterministic tests using synthetic data | Yes |
| `analyze_field.py` | Validated report CLI | Yes |
| `demo_field.py` | Reproducible synthetic walkthrough | Yes |
| `app.py` | Streamlit dashboard with synthetic default mode | Yes |
| `field_model/dashboard.py` | Framework-independent presentation transforms | Yes |
| `field_model/demo_data/` | Deterministic synthetic dashboard fixture | Yes |
| `docs/publication-scope.md` | Publication boundary | Yes |
| `data/private/` | Optional local private inputs | No; Git-ignored |
| `outputs/` | Generated local artifacts | Review before sharing; Git-ignored |

## Data contract and invariants

- Player identity uses stable player IDs, never DataFrame row position.
- A lineup must satisfy roster size, salary, position, and team constraints before analysis.
- Unknown IDs, ambiguous names, illegal rosters, and inconsistent metadata fail loudly.
- Randomized generation must accept and report a reproducible seed.
- Null-model and calibration results include their approximation or identification error.

## Exact commands

| Action | Command | Verified on/date |
|---|---|---|
| Doctor | `.\dev.cmd doctor` | Windows, 2026-08-15 |
| Setup | `.\dev.cmd setup` | Windows, 2026-08-15; locked sync |
| Test | `.\dev.cmd test` | Windows, 2026-10-06; 29 passed in full check |
| Lint | `.\dev.cmd lint` | Windows, 2026-08-15 |
| Full check | `.\dev.cmd check` | Windows, 2026-10-06; lint, 29 tests, demo, and diff passed |
| Demo | `.\dev.cmd demo` | Windows, 2026-08-15 |
| Dashboard | `.\dev.cmd app` | Launches Streamlit; dashboard verified on Windows, 2026-10-06 |

GitHub CI runs Python 3.11 and 3.12 with Ruff and pytest, plus built-wheel installation and dashboard smoke checks away from the source checkout.

A full local check writes a non-secret machine-readable receipt to `.artifacts/verification/latest.json`; the file is ignored by Git and can feed local tooling or future operational dashboards.

## Public/private boundary

Public-safe material includes reusable modeling infrastructure, deterministic synthetic fixtures, and honest limitations. Private-only material includes contest exports, account metadata, paid projections, private lineups, fitted production parameters, selection rules, and staking logic. Public demonstrations must use synthetic replacements and must not imply validated profitability.

## Known gaps

- No chronological held-out validation on legally obtained contest exports is published.
- No sport-specific correlated outcome model or production expected-value layer exists.
- The Linux/macOS wrapper exists but has not yet been verified on Linux; CI remains the verified Linux path.

## Dashboard data policy

Tracked dashboard examples are synthetic. User uploads remain in process memory
and are not written by the application. Public screenshots must use demo mode.
