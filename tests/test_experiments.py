import pytest
from pydantic import ValidationError

from growth_agent.experiments import (
    ExperimentBatch,
    ExperimentPlan,
    evaluate_experiments,
    holm_adjust,
    plan_experiment,
    wilson,
)


def batch(**changes):
    item = {
        "name": "signup",
        "control_visitors": 10000,
        "control_conversions": 1000,
        "treatment_visitors": 10000,
        "treatment_conversions": 1200,
        "required_per_arm": 10000,
        "fixed_horizon_complete": True,
    }
    item.update(changes)
    return ExperimentBatch(experiments=[item])


def test_wilson_known_reference_and_edges():
    # NIST/Wilson formula: 50 successes in 100 at 95%.
    assert wilson(50, 100) == pytest.approx([0.40383153, 0.59616847])
    assert wilson(0, 100)[0] == pytest.approx(0)
    assert wilson(100, 100)[1] == pytest.approx(1)


def test_holm_known_example_and_monotonicity():
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm_adjust([0.9, 0.8]) == [1, 1]


def test_positive_negative_and_null():
    result = evaluate_experiments(batch())["experiments"][0]
    assert result["decision"] == "positive_effect"
    assert result["p_value"] < 0.00001
    assert result["absolute_lift"] == pytest.approx(0.02)
    assert (
        evaluate_experiments(batch(treatment_conversions=800))["experiments"][0]["decision"]
        == "negative_effect"
    )
    assert (
        evaluate_experiments(batch(treatment_conversions=1000))["experiments"][0]["decision"]
        == "no_detected_difference"
    )


@pytest.mark.parametrize(
    "patch,warning",
    [
        ({"control_conversions": 0}, "insufficient_success_failure_counts_for_normal_test"),
        ({"treatment_visitors": 20000}, "sample_ratio_mismatch"),
        ({"fixed_horizon_complete": False}, "fixed_horizon_not_complete"),
        ({"required_per_arm": 20000}, "planned_sample_size_not_reached"),
    ],
)
def test_guardrails_prevent_premature_positive_claim(patch, warning):
    result = evaluate_experiments(batch(**patch))["experiments"][0]
    assert result["decision"] == "inconclusive"
    assert warning in result["warnings"]


def test_sample_size_increases_for_smaller_effect_and_more_comparisons():
    request = ExperimentPlan(baseline_rate=0.1, absolute_mde=0.02)
    one = plan_experiment(request)
    smaller = plan_experiment(request.model_copy(update={"absolute_mde": 0.01}))
    multiple = plan_experiment(request.model_copy(update={"comparisons": 5}))
    assert 3000 < one["per_arm_sample_size"] < 5000
    assert smaller["per_arm_sample_size"] > one["per_arm_sample_size"]
    assert multiple["per_arm_sample_size"] > one["per_arm_sample_size"]


def test_invalid_experiment_inputs():
    with pytest.raises(ValidationError):
        ExperimentPlan(baseline_rate=0.9, absolute_mde=0.2)
    with pytest.raises(ValidationError):
        batch(control_conversions=20000)
    item = batch().experiments[0]
    with pytest.raises(ValidationError):
        ExperimentBatch(experiments=[item, item])
