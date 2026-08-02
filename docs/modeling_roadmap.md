# Modeling roadmap

## The decision the model should support

The model is useful only if it improves contest and lineup decisions after
rake:

1. Which contests have the softest entry mixture?
2. Which candidate lineups have positive expected value under the payout table?
3. How should a portfolio trade projected score against duplication and
   correlated field exposure?

Player-level ownership decomposition is an intermediate diagnostic, not the
objective.

## Observation model before behavioral labels

Start with what contest exports directly identify:

- Exact lineup frequency
- Pairwise and player-pair overlap
- Salary remaining
- Team, game, and position stack structure
- Entry count per account when usernames are available
- Score and finish-rank distributions

Fit latent behavioral segments only after stable clusters appear in these
features. Neutral generator labels should describe statistical structure rather
than speculate about entrant skill or intent.

## Data schema

Persist one immutable snapshot per contest:

```text
contests:
  contest_id, sport, slate_id, start_time, entry_limit, field_size,
  buy_in, rake, payout_structure_id

entries:
  contest_id, entry_id, account_hash, player_ids, salary_used,
  final_score, finish_position, payout

players:
  slate_id, player_id, team, opponent, positions, salary,
  public_projection_snapshot, projected_ownership_snapshot

outcomes:
  slate_id, player_id, fantasy_points, status, minutes_or_opportunity
```

Keep projection and ownership snapshots timestamped. A projection downloaded
after lock creates leakage.

## Empirical baseline

Before fitting segments, benchmark simple models:

1. Independent Bernoulli ownership with roster repair
2. Maximum-entropy lineup model matching player marginals
3. Conditional logit or Plackett-Luce construction model
4. Nearest-neighbor resampling from similar historical contests

The segment mixture earns its complexity only if it improves held-out:

- Exact duplication calibration
- Player-pair and stack-frequency calibration
- Salary-remaining distribution
- Cash, p95, p99, and winning-score distributions
- Candidate-lineup payout and expected-value calibration

## Segment model

Use a hierarchical mixture whose weights vary by observable contest features:

```text
w_k(contest) = softmax(
    intercept_k
    + sport
    + log(field_size)
    + entry_limit
    + buy_in
    + slate_size
    + contest-format interactions
)
```

Each generator should produce a probability for an observed lineup, or at least
a simulation-based likelihood approximation. Matching a handful of moments
alone will generally leave the mixture unidentified.

Cache deterministic optimized menus by slate and projection snapshot. Noise,
choice-temperature, and mixture-weight calibration should reuse the menu rather
than repeatedly solving the same integer programs.

The implementation exposes two deliberately limited calibration tools:

- `fit_mixture_weights` fits nonnegative weights that sum to one and reports the
  ownership-design rank and condition number. A low RMSE with poor rank is not
  presented as identification.
- `calibrate_shared_menu` first reports exact menu coverage, then fits noise
  and choice temperature only to observed entries on that menu. Low coverage is
  a generator failure, not an invitation to tune harder.

These are diagnostics and initialization tools. Final inference should fit
joint lineup features across many held-out contests.

Useful generator families:

- Shared public-projection choice with heterogeneous sources and noise
- Salary- and recency-biased sequential selection
- Optimizer portfolios with explicit uniqueness and exposure constraints
- Historical-lineup resampling conditioned on contest features

Do not model a professional segment as uniformly stronger. It is a portfolio
process with projection disagreement, correlation preferences, exposure caps,
and duplication avoidance.

## Outcome and payout layer

Field generation must remain separate from player outcomes:

```text
field lineups -> correlated slate outcomes -> ranks and ties -> payout after rake
```

Player outcomes need sport-specific correlations and opportunity uncertainty.
For soccer, this includes team scoring states, assists, clean sheets, goalkeeper
interactions, substitutions, and starting-lineup uncertainty.

For candidate lineup `L`, estimate:

```text
EV(L) = mean_simulated_payout(L, field, outcomes) - entry_fee
```

This automatically prices projection, leverage, duplication, and payout shape.
A handcrafted "fade value" should not replace it.

## Validation protocol

Split chronologically and group by slate so the same slate never appears in
both train and test. Report results by sport, field size, entry limit, and
buy-in band.

Use posterior predictive or simulation calibration plots rather than a single
average error. Bootstrap entire contests, not individual entries, because
entries within a contest are dependent.

The first production milestone is not a sophisticated latent model. It is a
data pipeline that can reproduce held-out lineup concentration and duplication
better than the marginal-ownership baselines.
