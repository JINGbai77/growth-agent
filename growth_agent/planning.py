import heapq
import math

from pydantic import Field, model_validator

from growth_agent.models import Anomaly, Contract


class ScenarioRequest(Contract):
    anomaly_id: str
    recovery_fraction: float = Field(default=0.5, gt=0, le=1)


def recovery_scenarios(anomaly: Anomaly, fraction: float) -> dict:
    """Interventions on factors, not causal forecasts or expected experiment outcomes."""
    if anomaly.direction != "drop":
        raise ValueError("Recovery scenarios require a drop anomaly")
    visitors = anomaly.observed_visitors
    conversion = anomaly.observed_conversion
    target_v = visitors + fraction * max(0, anomaly.baseline_visitors - visitors)
    target_c = conversion + fraction * max(0, anomaly.baseline_conversion - conversion)
    scenarios = []
    for name, new_v, new_c in (
        ("traffic_only", target_v, conversion),
        ("conversion_only", visitors, target_c),
        ("joint_recovery", target_v, target_c),
    ):
        users = new_v * new_c
        scenarios.append(
            {
                "name": name,
                "assumed_visitors": new_v,
                "assumed_conversion": new_c,
                "modeled_users": users,
                "incremental_users": users - anomaly.observed_users,
            }
        )
    return {
        "anomaly_id": anomaly.id,
        "recovery_fraction": fraction,
        "scenarios": scenarios,
        "assumptions": [
            "Restores the selected fraction of a factor's gap to its historical baseline.",
            "Other factors remain fixed; interventions have no cross-channel spillovers.",
            "No cost or probability of achieving the intervention has been estimated.",
            "Modeled counts are conditional scenarios, not measured uplift or causal estimates.",
        ],
    }


class ChannelCurve(Contract):
    channel: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    max_incremental_users: float = Field(gt=0, le=10**8)
    scale_budget: float = Field(gt=0, le=10**9)
    cap: int = Field(ge=0, le=10**9)
    conservative_factor: float = Field(default=0.7, ge=0, le=1)

    def gain(self, budget: int, conservative: bool = True) -> float:
        factor = self.conservative_factor if conservative else 1
        return factor * self.max_incremental_users * (-math.expm1(-budget / self.scale_budget))


class BudgetRequest(Contract):
    total_budget: int = Field(ge=0, le=10**9)
    quantum: int = Field(default=100, ge=1, le=10**7)
    channels: list[ChannelCurve] = Field(min_length=1, max_length=50)
    assumption_source: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_problem(self):
        if self.total_budget // self.quantum > 10000:
            raise ValueError("Use a larger quantum: maximum 10,000 allocation steps")
        names = [channel.channel for channel in self.channels]
        if len(set(names)) != len(names):
            raise ValueError("Channel names must be unique")
        return self


def allocate_budget(request: BudgetRequest) -> dict:
    """Optimal discrete allocation for separable increasing concave response curves."""
    curves = {channel.channel: channel for channel in request.channels}
    allocations = dict.fromkeys(sorted(curves), 0)
    heap = []
    quantum = request.quantum
    for name, curve in curves.items():
        if curve.cap >= quantum and curve.conservative_factor > 0:
            heapq.heappush(heap, (-curve.gain(quantum), name))
    spent = 0
    while heap and spent + quantum <= request.total_budget:
        _, name = heapq.heappop(heap)
        curve = curves[name]
        allocations[name] += quantum
        spent += quantum
        current = allocations[name]
        if current + quantum <= curve.cap:
            marginal = curve.gain(current + quantum) - curve.gain(current)
            if marginal > 0:
                heapq.heappush(heap, (-marginal, name))
    return {
        "algorithm": "discrete_concave_marginal_allocation",
        "total_budget": request.total_budget,
        "allocated_budget": spent,
        "unallocated_budget": request.total_budget - spent,
        "quantum": quantum,
        "allocations": [
            {
                "channel": name,
                "budget": amount,
                "cap": curves[name].cap,
                "modeled_incremental_users": curves[name].gain(amount, conservative=False),
                "conservative_modeled_users": curves[name].gain(amount),
            }
            for name, amount in allocations.items()
        ],
        "objective_value": sum(curves[name].gain(amount) for name, amount in allocations.items()),
        "assumption_source": request.assumption_source,
        "requires_human_approval": True,
        "limitations": [
            "Response-curve parameters and conservative factors are supplied "
            "assumptions, not fitted.",
            "Optimal only for this separable concave model on the chosen budget grid.",
            "Assumes one currency, one planning horizon and no cross-channel interactions.",
            "No advertising account is connected and no money is spent.",
        ],
    }
