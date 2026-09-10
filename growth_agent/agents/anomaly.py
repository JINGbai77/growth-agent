from collections import defaultdict, deque
from datetime import timedelta
from math import sqrt
from statistics import median

from growth_agent.models import Anomaly, DetectionOptions, GrowthRecord


class AnomalyAgent:
    """Causal-in-time robust baselines, independently fitted for every channel."""

    def detect(self, records: list[GrowthRecord], options: DetectionOptions):
        history: dict[str, deque[GrowthRecord]] = defaultdict(deque)
        anomalies = []
        evaluated = 0
        gap_channels = set()
        for row in sorted(records, key=lambda r: (r.date, r.channel)):
            window = history[row.channel]
            if window and (row.date - window[-1].date).days > 1:
                gap_channels.add(row.channel)
            cutoff = row.date - timedelta(days=options.lookback_days)
            while window and window[0].date < cutoff:
                window.popleft()
            if len(window) >= options.min_history:
                same_day = [r for r in window if r.date.weekday() == row.date.weekday()]
                if options.seasonality == "weekday":
                    if len(same_day) < options.min_seasonal_samples:
                        window.append(row)
                        continue
                    baseline = same_day
                    baseline_method = "same_weekday"
                else:
                    baseline = list(window)
                    baseline_method = "rolling"
                users = [r.new_users for r in baseline]
                expected = float(median(users))
                mad = median([abs(v - expected) for v in users])
                # Counting-noise floor prevents tiny-baseline and zero-variance explosions.
                scale = max(1.4826 * mad, sqrt(max(expected, 1)), 1)
                delta = row.new_users - expected
                relative = delta / max(expected, 1)
                score = delta / scale
                evaluated += 1
                if (
                    abs(score) >= options.z_threshold
                    and abs(relative) >= options.min_relative_change
                    and abs(delta) >= options.min_absolute_change
                ):
                    visitors = float(median([r.visitors for r in baseline]))
                    anomalies.append(
                        Anomaly(
                            id=f"{row.channel}:{row.date.isoformat()}",
                            date=row.date,
                            channel=row.channel,
                            direction="drop" if delta < 0 else "spike",
                            observed_users=row.new_users,
                            expected_users=expected,
                            delta_users=delta,
                            relative_change=relative,
                            robust_z=score,
                            baseline_method=baseline_method,
                            baseline_samples=len(baseline),
                            baseline_visitors=visitors,
                            baseline_conversion=expected / visitors if visitors else 0,
                            observed_visitors=row.visitors,
                            observed_conversion=row.new_users / row.visitors if row.visitors else 0,
                            observed_spend=row.spend,
                            baseline_spend=float(median([r.spend for r in baseline])),
                        )
                    )
            window.append(row)
        warnings = [f"missing_dates:{channel}" for channel in sorted(gap_channels)]
        skipped = len(records) - evaluated
        if skipped:
            warnings.append(f"insufficient_history:{skipped} rows were not evaluated")
        return anomalies, evaluated, warnings
