# Contributing

## Development setup

```bash
sh scripts/dev.sh setup
sh scripts/dev.sh check
```

On Windows, use `.\dev.cmd setup` followed by `.\dev.cmd check`.

## Pull requests

- Add or update tests for behavioral changes.
- Keep player and contest fixtures synthetic.
- Document new assumptions in the relevant public API docstring.
- Preserve stable player-ID semantics across ingestion and simulation.
- Report realized baseline marginals whenever adding a structural comparison.

## Data policy

Do not commit contest exports, account names, credentials, paid projections, or
data whose redistribution terms are unclear. Small deterministic synthetic
fixtures are preferred for tests and demonstrations.
