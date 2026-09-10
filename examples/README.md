# API examples

`sample_request.json` contains simulated nonseasonal records with one injected traffic drop. Submit
it to `/v1/analyze` or `/v1/jobs`.

Create a recovery scenario for an anomaly returned by the source report:

```json
{"anomaly_id": "ads:2025-01-20", "recovery_fraction": 0.5}
```

Create a hypothetical constrained budget plan. Parameters are assumptions, not fitted effects:

```json
{
  "total_budget": 10000,
  "quantum": 100,
  "assumption_source": "simulated interview example",
  "channels": [
    {"channel": "ads", "max_incremental_users": 500, "scale_budget": 4000,
     "cap": 8000, "conservative_factor": 0.7}
  ]
}
```

Evaluate one fixed-horizon randomized experiment:

```json
{
  "experiments": [{
    "name": "signup-copy", "control_visitors": 10000, "control_conversions": 1000,
    "treatment_visitors": 10000, "treatment_conversions": 1200,
    "required_per_arm": 10000, "fixed_horizon_complete": true
  }]
}
```
