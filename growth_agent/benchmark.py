import math
import platform
from datetime import UTC, datetime, timedelta
from statistics import mean, median
from time import perf_counter

from growth_agent import __version__
from growth_agent.config import Settings
from growth_agent.data.generator import SCENARIOS, generate_data
from growth_agent.models import AnalysisRequest
from growth_agent.service.pipeline import GrowthPipeline


def metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def mean_baseline(request: AnalysisRequest) -> set[str]:
    """Causal comparator with the same warm-up, stronger than the original global mean."""
    histories = {}
    predicted = set()
    warmup = request.options.min_history
    if request.options.seasonality == "weekday":
        warmup = max(warmup, request.options.min_seasonal_samples * 7)
    for row in sorted(request.records, key=lambda r: (r.date, r.channel)):
        window = histories.setdefault(row.channel, [])
        cutoff = row.date - timedelta(days=request.options.lookback_days)
        window[:] = [r for r in window if r.date >= cutoff]
        if len(window) >= warmup:
            expected = mean(r.new_users for r in window)
            if abs(row.new_users - expected) >= max(10, 0.3 * expected):
                predicted.add(f"{row.channel}:{row.date.isoformat()}")
        window.append(row)
    return predicted


def evaluate(seeds: int = 20) -> dict:
    if not 1 <= seeds <= 100:
        raise ValueError("seeds must be between 1 and 100")
    pipeline = GrowthPipeline(Settings(_env_file=None, llm_enabled=False))
    totals = {name: [0, 0, 0] for name in ("robust", "rolling_mean")}
    per_scenario = {}
    correct_driver = detected_labeled = evaluated_count = 0
    for scenario in SCENARIOS:
        counts = [0, 0, 0]
        for seed in range(seeds):
            payload, labels = generate_data(seed=seed, scenario=scenario)
            request = AnalysisRequest.model_validate(payload)
            report = pipeline.run(request)
            evaluated_count += report.evaluated_count
            expected = {label["anomaly_id"] for label in labels}
            expected_drivers = {label["anomaly_id"]: label["driver"] for label in labels}
            for name, predicted in (
                ("robust", {a.id for a in report.anomalies}),
                ("rolling_mean", mean_baseline(request)),
            ):
                outcomes = [
                    len(predicted & expected),
                    len(predicted - expected),
                    len(expected - predicted),
                ]
                totals[name] = [a + b for a, b in zip(totals[name], outcomes, strict=True)]
                if name == "robust":
                    counts = [a + b for a, b in zip(counts, outcomes, strict=True)]
            for finding in report.findings:
                if finding.anomaly_id in expected:
                    detected_labeled += 1
                    correct_driver += finding.driver == expected_drivers[finding.anomaly_id]
        per_scenario[scenario] = metrics(*counts)
    return {
        "data_kind": "synthetic",
        "seeds": list(range(seeds)),
        "scenarios": len(SCENARIOS),
        "datasets": seeds * len(SCENARIOS),
        "records_per_dataset": 252,
        "evaluated_records": evaluated_count,
        "detectors": {name: metrics(*counts) for name, counts in totals.items()},
        "per_scenario": per_scenario,
        "driver_accuracy_on_detected_labels": (
            correct_driver / detected_labeled if detected_labeled else None
        ),
        "detected_labels_for_driver_scoring": detected_labeled,
        "limitations": [
            "Generated scenarios share one simulator; results are not business impact.",
            "Labels cover injected events only; noise and gradual drift are treated as negatives.",
            "Warm-up rows are excluded; sustained events are scored per point, not per incident.",
            "Driver labels describe injected arithmetic factors, not real-world causal truth.",
        ],
    }


def latency(iterations: int = 30) -> list[dict]:
    if not 1 <= iterations <= 1000:
        raise ValueError("iterations must be between 1 and 1000")
    pipeline = GrowthPipeline(Settings(_env_file=None, llm_enabled=False))
    results = []
    for days in (84, 3333):
        payload, _ = generate_data(days=days)
        for _ in range(3):
            pipeline.run(AnalysisRequest.model_validate(payload))
        samples = []
        for _ in range(iterations):
            before = perf_counter()
            report = pipeline.run(AnalysisRequest.model_validate(payload))
            report.model_dump_json()
            samples.append((perf_counter() - before) * 1000)
        samples.sort()
        results.append(
            {
                "records": len(payload["records"]),
                "iterations": iterations,
                "median_ms": round(median(samples), 3),
                "p95_ms": round(samples[max(0, math.ceil(0.95 * len(samples)) - 1)], 3),
                "min_ms": round(samples[0], 3),
                "max_ms": round(samples[-1], 3),
            }
        )
    return results


def benchmark(seeds: int = 20, iterations: int = 30) -> dict:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "engine_version": __version__,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "method": "Validation + offline pipeline + JSON serialization; 3 warmups; no HTTP/DB/LLM",
        "evaluation": evaluate(seeds),
        "latency": latency(iterations),
    }
