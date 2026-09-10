import math
from statistics import NormalDist

from pydantic import Field, model_validator

from growth_agent.models import Contract


class ExperimentPlan(Contract):
    baseline_rate: float = Field(gt=0, lt=1)
    absolute_mde: float = Field(gt=0.00001, lt=1)
    power: float = Field(default=0.8, ge=0.5, le=0.99)
    alpha: float = Field(default=0.05, ge=0.001, le=0.2)
    comparisons: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def valid_alternative(self):
        if self.baseline_rate + self.absolute_mde >= 1:
            raise ValueError("baseline_rate + absolute_mde must be less than one")
        return self


def plan_experiment(request: ExperimentPlan) -> dict:
    p1 = request.baseline_rate
    p2 = p1 + request.absolute_mde
    average = (p1 + p2) / 2
    alpha = request.alpha / request.comparisons
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(request.power)
    n = math.ceil(
        (
            (
                z_alpha * math.sqrt(2 * average * (1 - average))
                + z_power * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
            )
            / request.absolute_mde
        )
        ** 2
    )
    return {
        "per_arm_sample_size": n,
        "total_sample_size": 2 * n,
        "planning_alpha": alpha,
        "power": request.power,
        "absolute_mde": request.absolute_mde,
        "method": "two-sided equal-allocation normal approximation; Bonferroni planning alpha",
        "assumptions": [
            "Random assignment; independent Bernoulli outcomes; one observation per user.",
            "Pre-register sample size, primary metric and fixed analysis horizon; "
            "no repeated peeking.",
            "Approximate power; validate planning assumptions on real baseline data.",
        ],
    }


class ExperimentResult(Contract):
    name: str = Field(min_length=1, max_length=100)
    control_visitors: int = Field(ge=1, le=10**9)
    control_conversions: int = Field(ge=0, le=10**9)
    treatment_visitors: int = Field(ge=1, le=10**9)
    treatment_conversions: int = Field(ge=0, le=10**9)
    planned_treatment_share: float = Field(default=0.5, ge=0.05, le=0.95)
    required_per_arm: int = Field(ge=1, le=10**9)
    fixed_horizon_complete: bool = False

    @model_validator(mode="after")
    def valid_counts(self):
        if (
            self.control_conversions > self.control_visitors
            or self.treatment_conversions > self.treatment_visitors
        ):
            raise ValueError("Conversions cannot exceed visitors")
        return self


class ExperimentBatch(Contract):
    experiments: list[ExperimentResult] = Field(min_length=1, max_length=20)
    alpha: float = Field(default=0.05, ge=0.001, le=0.2)

    @model_validator(mode="after")
    def unique_names(self):
        names = [experiment.name for experiment in self.experiments]
        if len(set(names)) != len(names):
            raise ValueError("Experiment names must be unique")
        return self


def wilson(successes: int, trials: int, alpha: float = 0.05) -> list[float]:
    z = NormalDist().inv_cdf(1 - alpha / 2)
    rate = successes / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials))
    margin /= denominator
    return [max(0, center - margin), min(1, center + margin)]


def holm_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(p_values) - rank) * p_values[index])
        adjusted[index] = min(1, running)
    return adjusted


def evaluate_experiments(batch: ExperimentBatch) -> dict:
    rows = []
    for item in batch.experiments:
        n0, n1 = item.control_visitors, item.treatment_visitors
        x0, x1 = item.control_conversions, item.treatment_conversions
        p0, p1 = x0 / n0, x1 / n1
        pooled = (x0 + x1) / (n0 + n1)
        variance = pooled * (1 - pooled) * (1 / n0 + 1 / n1)
        sufficient_counts = min(x0, x1, n0 - x0, n1 - x1) >= 10
        p_value = (
            math.erfc(abs(p1 - p0) / math.sqrt(2 * variance))
            if variance and sufficient_counts
            else None
        )
        expected1 = (n0 + n1) * item.planned_treatment_share
        expected0 = n0 + n1 - expected1
        chi_square = (n1 - expected1) ** 2 / expected1 + (n0 - expected0) ** 2 / expected0
        srm_p = math.erfc(math.sqrt(chi_square / 2))
        warnings = []
        if not sufficient_counts:
            warnings.append("insufficient_success_failure_counts_for_normal_test")
        if srm_p < 0.001:
            warnings.append("sample_ratio_mismatch")
        if not item.fixed_horizon_complete:
            warnings.append("fixed_horizon_not_complete")
        if min(n0, n1) < item.required_per_arm:
            warnings.append("planned_sample_size_not_reached")
        rows.append(
            {
                "name": item.name,
                "control_rate": p0,
                "treatment_rate": p1,
                "absolute_lift": p1 - p0,
                "relative_lift": (p1 - p0) / p0 if p0 else None,
                "control_wilson_interval": wilson(x0, n0, batch.alpha),
                "treatment_wilson_interval": wilson(x1, n1, batch.alpha),
                "p_value": p_value,
                "sample_ratio_mismatch_p": srm_p,
                "warnings": warnings,
            }
        )
    # Keep invalid hypotheses in the declared family with p=1, preventing silent family shrinkage.
    adjusted = holm_adjust([r["p_value"] if r["p_value"] is not None else 1 for r in rows])
    for row, adjusted_p in zip(rows, adjusted, strict=True):
        row["holm_adjusted_p"] = adjusted_p
        if row["warnings"]:
            row["decision"] = "inconclusive"
        elif adjusted_p <= batch.alpha:
            row["decision"] = "positive_effect" if row["absolute_lift"] > 0 else "negative_effect"
        else:
            row["decision"] = "no_detected_difference"
    return {
        "experiments": rows,
        "family_size": len(rows),
        "alpha": batch.alpha,
        "method": "pooled two-proportion z test with Holm family-wise adjustment",
        "limitations": [
            "Fixed-horizon randomized independent user outcomes required; "
            "assumptions not verified.",
            "Wilson intervals describe each arm separately and are not simultaneous "
            "lift intervals.",
            "Non-significance is not evidence of equivalence; significance is not business value.",
            "SRM uses a large-sample chi-square diagnostic with threshold 0.001.",
        ],
    }
