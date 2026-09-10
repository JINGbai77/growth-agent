import random
from datetime import date, timedelta

from growth_agent.models import AnalysisRequest

SCENARIOS = (
    "normal",
    "weekly",
    "traffic_drop",
    "conversion_drop",
    "mixed_drop",
    "spike",
    "sustained_drop",
    "high_noise",
    "gradual_drift",
)


def generate_data(days: int = 84, seed: int = 42, scenario: str = "mixed_drop"):
    """Fixed dates and local PRNG. Labels are generated separately from request payloads."""
    if days < 35 or days > 3333:
        raise ValueError("days must be between 35 and 3333")
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    rng = random.Random(seed)
    records = []
    labels = []
    start = date(2025, 1, 6)
    configs = [("ads", 8000, 0.1, 1500), ("organic", 3000, 0.08, 0), ("referral", 1000, 0.15, 100)]
    event_day = days - 8
    for day in range(days):
        current = start + timedelta(days=day)
        for channel, volume, rate, spend in configs:
            seasonal = 0.65 if current.weekday() >= 5 and scenario != "normal" else 1
            noise = 0.18 if scenario == "high_noise" else 0.025
            visitors = max(0, round(volume * seasonal * (1 + rng.gauss(0, noise))))
            cvr = min(1, max(0, rate * (1 + rng.gauss(0, noise / 2))))
            if scenario == "gradual_drift":
                visitors = round(visitors * (1 + day * 0.002))
            active = channel == "ads" and (
                day == event_day
                or scenario == "sustained_drop"
                and event_day <= day < event_day + 5
            )
            driver = None
            if active:
                if scenario in {"traffic_drop", "sustained_drop"}:
                    visitors = round(visitors * 0.4)
                    driver = "traffic"
                elif scenario == "conversion_drop":
                    cvr *= 0.4
                    driver = "conversion"
                elif scenario == "mixed_drop":
                    visitors = round(visitors * 0.65)
                    cvr *= 0.6
                    driver = "mixed"
                elif scenario == "spike":
                    visitors = round(visitors * 1.7)
                    driver = "traffic"
            records.append(
                {
                    "date": current.isoformat(),
                    "channel": channel,
                    "visitors": visitors,
                    "new_users": round(visitors * cvr),
                    "spend": spend,
                }
            )
            if driver:
                labels.append({"anomaly_id": f"{channel}:{current.isoformat()}", "driver": driver})
    return {"records": records}, labels


def demo_request() -> AnalysisRequest:
    payload, _ = generate_data()
    return AnalysisRequest.model_validate(payload)
