# DFS Field Model repository rules

This file adds repository-specific requirements to the global Codex working agreements.

## Orientation

- Read `README.md`, `docs/codex-context.md`, `pyproject.toml`, relevant tests, and `.github/workflows/ci.yml` before material changes.
- This is a sanitized public research repository. All fixtures, defaults, demos, and reported outputs must remain deterministic and synthetic.
- Preserve unrelated work and confirm the active branch and dirty files before editing.

## Canonical commands

- Environment diagnosis: `.\dev.cmd doctor`
- Setup: `.\dev.cmd setup`
- Test: `.\dev.cmd test`
- Lint: `.\dev.cmd lint`
- Full verification: `.\dev.cmd check`
- Demo: `.\dev.cmd demo`
- Linux/macOS equivalents: `sh scripts/dev.sh <doctor|setup|test|lint|check|demo>`.
- A full check writes an ignored, non-secret receipt to `.artifacts/verification/latest.json`.

## Non-negotiable invariants

- Keep stable player IDs independent of DataFrame row indices.
- Validate every imported lineup before calculating diagnostics.
- Report null-model marginal error and mixture identification diagnostics; never present illustrative generator defaults as fitted evidence.
- Do not add real contest exports, account identifiers, private lineups, paid projections, vendor payloads, validated production parameters, selection rules, staking logic, credentials, endpoints, or infrastructure details.

## Scope and approval gates

- Normal scope: `field_model/`, `tests/`, public documentation, CLI modules, and deterministic examples.
- Require approval before dependency changes, public API breaking changes, licensing changes, release publication, or GitHub writes.
- Do not turn this repository into a wagering or production expected-value product.

## Definition of done

- `.\dev.cmd check` passes and writes a successful verification receipt.
- Changed behavior has deterministic test coverage and relevant documentation.
- The demo still runs and limitations remain explicit.
- The final diff contains no private data, licensed inputs, secrets, local paths, accidental artifacts, or exaggerated performance claims.
