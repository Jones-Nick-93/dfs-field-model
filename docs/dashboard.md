# Dashboard usage

## Start locally

```bash
python -m pip install -e ".[app]"
streamlit run app.py
```

Demo mode is the default. It generates two explicit synthetic lineup processes,
combines them into a field, and compares that field with a legal
ownership-weighted null model. The deterministic generated result is tracked as
a small fixture so the browser never runs the optimizer during initial load.

Regenerate that fixture deliberately with:

```bash
python scripts/build_demo_fixture.py
```

## Views

### Overview

Shows exact duplication, lineup HHI, effective lineup count, salary remaining,
and observed-versus-null errors. The null comparison is useful only when its
realized player-ownership error is inspected alongside structural error.

### Ownership

Compares observed marginal player ownership with the null field. The dashboard
does not assume the null perfectly reproduces its proposal weights.

### Pair structure

Shows player pairs whose observed co-ownership exceeds the product of their
marginal ownership. This detects dependence but does not identify its cause.

### Lineup inspector

Displays the roster, salary, exact duplication count, largest team stack, and
projection sum for one complete entry.

### Method

States what is directly measured and what the current project cannot establish.

## Upload privacy

Uploaded files are read into the active Streamlit process and are not written by
the dashboard. That is an application behavior, not a guarantee about an
external hosting provider. Review the host's retention and logging policy before
uploading non-public data to a deployed instance.

Public screenshots and demonstrations should use synthetic demo mode.

## Expected schemas

The player pool requires:

```text
player_id, player, team, pos, salary,
true_mean, consensus, fame, recency
```

Contest entries may use wide, long, or DraftKings-style layout. See
[contest ingestion](contest_ingestion.md) for details.
