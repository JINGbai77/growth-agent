import itertools
import math

import pytest
from pydantic import ValidationError

from growth_agent.planning import BudgetRequest, allocate_budget, recovery_scenarios
from growth_agent.service.pipeline import GrowthPipeline


def test_scenarios_obey_intervention_factors(analysis_request, settings):
    anomaly = GrowthPipeline(settings).run(analysis_request).anomalies[0]
    result = recovery_scenarios(anomaly, 0.5)
    by_name = {s["name"]: s for s in result["scenarios"]}
    assert by_name["traffic_only"]["modeled_users"] == pytest.approx(700)
    assert by_name["conversion_only"]["incremental_users"] == pytest.approx(0)
    assert by_name["joint_recovery"]["modeled_users"] == pytest.approx(700)
    spike = anomaly.model_copy(update={"direction": "spike"})
    with pytest.raises(ValueError):
        recovery_scenarios(spike, 0.5)


@pytest.mark.parametrize("budget", [0, 10, 30, 70, 101])
def test_optimizer_matches_exhaustive_search(budget):
    request = BudgetRequest(
        total_budget=budget,
        quantum=10,
        assumption_source="synthetic test",
        channels=[
            {"channel": "ads", "max_incremental_users": 100, "scale_budget": 30, "cap": 60},
            {
                "channel": "referral",
                "max_incremental_users": 80,
                "scale_budget": 20,
                "cap": 40,
                "conservative_factor": 0.5,
            },
        ],
    )
    candidates = []
    for a, b in itertools.product(range(0, 61, 10), range(0, 41, 10)):
        if a + b <= budget:
            candidates.append(request.channels[0].gain(a) + request.channels[1].gain(b))
    result = allocate_budget(request)
    assert result["objective_value"] == pytest.approx(max(candidates))
    assert result["allocated_budget"] <= budget
    assert all(row["budget"] <= row["cap"] for row in result["allocations"])
    assert result["unallocated_budget"] == budget - result["allocated_budget"]


def test_concave_gains_and_zero_confidence_channel():
    request = BudgetRequest(
        total_budget=100,
        quantum=10,
        assumption_source="assumed",
        channels=[
            {
                "channel": "one",
                "max_incremental_users": 100,
                "scale_budget": 10,
                "cap": 100,
                "conservative_factor": 0,
            },
        ],
    )
    result = allocate_budget(request)
    assert result["allocated_budget"] == 0
    curve = request.channels[0].model_copy(update={"conservative_factor": 1})
    increments = [curve.gain(i + 10) - curve.gain(i) for i in range(0, 100, 10)]
    assert increments == sorted(increments, reverse=True)
    assert math.isfinite(sum(increments))


def test_budget_validation():
    channel = {"channel": "ads", "max_incremental_users": 10, "scale_budget": 10, "cap": 10}
    for kwargs in (
        {"total_budget": 10001, "quantum": 1, "channels": [channel]},
        {"total_budget": 100, "channels": [channel, channel]},
    ):
        with pytest.raises(ValidationError):
            BudgetRequest(**kwargs, assumption_source="test")
