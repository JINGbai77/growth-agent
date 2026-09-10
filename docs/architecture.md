# Architecture and design decisions

## Goal and boundaries

The system supports a human growth analyst from detection through validation. It deliberately
does not execute marketing changes. Every recommendation carries a human-approval flag, a success
metric and guardrails. Statistical output remains available when the optional model is offline.

## Evidence flow

`GrowthRecord` is the source contract. Records must be unique by date and channel, users cannot
exceed visitors, numeric values are bounded and finite, and unknown fields fail validation.

The Anomaly Agent sorts rows, partitions by channel, and only uses rows earlier than the candidate
date. With weekday seasonality it abstains until eight earlier matching weekdays exist. Expected
users are the median and scale is the larger of scaled MAD, a Poisson counting-noise floor and one.
An alert must pass robust-z, relative-change and absolute-change gates. Missing dates become report
warnings. The detector supports an explicit nonseasonal rolling mode.

The Analysis Agent uses the symmetric two-factor decomposition:

```text
traffic = (V1 − V0) × (C1 + C0) / 2
conversion = (C1 − C0) × (V1 + V0) / 2
traffic + conversion = V1×C1 − V0×C0
```

This invariant is tested across traffic, conversion, mixed, spike and zero-baseline cases. It is
an arithmetic explanation of the metric change, not proof of why the factors changed.

The Decision Agent maps dominant factors to versioned playbooks. It produces investigation steps,
owners, success metrics and guardrails. Recommendations are proposals, and never modify external
systems.

## Decision lab

Recovery scenarios interpolate selected observed factors toward their historical baseline. They
answer conditional “what if” questions and state all assumptions. They are not forecasts.

The budget planner accepts assumed saturating response curves
`gain(b) = max_users × (1 − exp(−b / scale))`, channel caps, a budget quantum and a conservative
factor. A priority queue repeatedly chooses the largest next marginal gain. For separable increasing
concave functions this is optimal on the discrete grid; tests compare it with exhaustive enumeration.
Because response parameters are supplied rather than estimated, output is labeled modeled and
requires approval.

The experiment module plans equal-allocation two-sided proportion tests with a Bonferroni planning
alpha. Evaluation reports per-arm Wilson intervals, a pooled two-proportion z test, Holm family-wise
adjustment and sample-ratio-mismatch diagnostics. Results are inconclusive when counts are too small,
the fixed horizon is incomplete, planned sample size is not reached or SRM is detected.

## Durable execution

Synchronous analysis is available for interactive use. Asynchronous jobs use a bounded thread pool,
idempotency keys and SQLite WAL persistence. Inputs, status, reports, derived artifacts, engine
version and lineage are stored. On process start, queued/running rows become `interrupted` rather
than being silently replayed. An OS-held lease prevents two local schedulers from owning one SQLite
database; Docker therefore runs one worker. Replay creates a new job linked to its source.

This is an intentional single-node design. A horizontally scaled version would use Postgres and a
durable broker, add transactional claiming/leases, authentication, tenancy, cancellation, retention,
metrics and distributed tracing.

## LLM containment

The local reasoner receives at most ten ranked anomalies and their deterministic findings. A system
message treats supplied fields as data. Ollama receives a JSON schema, temperature zero and an output
token bound. Returned content is validated against Pydantic contracts and may only refer to supplied
anomaly IDs. Timeouts, HTTP failures, invalid JSON/schema, duplicate IDs and unknown IDs produce a
sanitized fallback status. Request bodies, provider URLs, exception messages and model content are
excluded from structured logs.

## Evaluation protocol

The checked-in simulator provides nine scenarios: normal, weekly seasonality, traffic drop,
conversion drop, mixed drop, spike, sustained drop, high noise and gradual drift. Each dataset uses
a local seeded random generator and fixed dates. Evaluation reports micro precision/recall/F1,
per-scenario outcomes, injected-factor classification, evaluated-record count and a causal rolling
mean comparator. Warm-up rows are excluded; sustained points are scored separately.

This protocol is reproducible but synthetic and shares assumptions with the implemented detector.
Its purpose is regression testing and transparent comparison. External labeled data is required for
claims about production accuracy.

## Deliberate limitations

- Input supports daily aggregate funnel data, not event-level causal estimation.
- Same-weekday MAD can over-alert on volatile series; the benchmark exposes this failure mode.
- Scenarios assume factor independence, while real channels may interact.
- Budget response curves are inputs; fitting them from randomized geo or incrementality tests is out
  of scope.
- The z test uses a large-sample approximation and fixed-horizon assumptions.
- SQLite and the in-process executor provide durability on one node, not distributed guarantees.
