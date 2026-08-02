# Repository guidance

## Public boundary

- Keep all fixtures deterministic and synthetic.
- Do not add real contest exports, account identifiers, private lineups, paid
  projections, vendor payloads, validated production parameters, selection
  rules, staking logic, credentials, endpoints, or infrastructure details.
- Treat generator settings as illustrative hypotheses and state that limitation
  anywhere they are presented.

## Verification

- Run `pytest -q`, `ruff check .`, and `python demo_field.py` before publishing.
- Preserve stable player-ID semantics and validate every imported lineup before
  calculating diagnostics.
