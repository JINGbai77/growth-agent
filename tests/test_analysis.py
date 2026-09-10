import copy
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from growth_agent.data.generator import generate_data
from growth_agent.models import AnalysisRequest, DetectionOptions
from growth_agent.service.pipeline import GrowthPipeline


def test_traffic_drop_and_evidence_chain(analysis_request, settings):
    report = GrowthPipeline(settings).run(analysis_request)
    assert len(report.anomalies) == 1
    anomaly = report.anomalies[0]
    finding = report.findings[0]
    assert anomaly.expected_users == 1000
    assert anomaly.baseline_method == "same_weekday"
    assert anomaly.delta_users == -600
    assert finding.driver == "traffic"
    assert finding.traffic_contribution == pytest.approx(-600)
    assert finding.conversion_contribution == pytest.approx(0)
    assert report.actions[0].anomaly_id == finding.anomaly_id == anomaly.id
    assert report.actions[0].requires_human_approval
    assert report.skipped_count == 56
    assert report.evaluated_count == 8


@pytest.mark.parametrize(
    "visitors,users,driver",
    [
        (10000, 400, "conversion"),
        (6000, 360, "mixed"),
        (17000, 1700, "traffic"),
        (0, 0, "mixed"),
    ],
)
def test_factor_decomposition_conserves_delta(payload, settings, visitors, users, driver):
    payload["records"][-1].update(visitors=visitors, new_users=users)
    report = GrowthPipeline(settings).run(AnalysisRequest.model_validate(payload))
    a, f = report.anomalies[0], report.findings[0]
    assert f.driver == driver
    assert f.traffic_contribution + f.conversion_contribution == pytest.approx(a.delta_users)
    assert f.observed_cac is None if users == 0 else f.observed_cac == 2000 / users
    if users == 1700:
        assert a.direction == "spike"
        assert "increase" in report.actions[0].recommendation


def test_separate_channel_scales(payload, settings):
    payload["records"][-1].update(visitors=10000, new_users=1000)
    organic = [
        dict(row, channel="organic", visitors=100, new_users=10) for row in payload["records"]
    ]
    payload["records"] += organic
    report = GrowthPipeline(settings).run(AnalysisRequest.model_validate(payload))
    assert report.anomalies == []


def test_future_data_cannot_change_past_detection(payload, settings):
    pipeline = GrowthPipeline(settings)
    before = pipeline.run(AnalysisRequest.model_validate(payload))
    future = copy.deepcopy(payload)
    end = date.fromisoformat(payload["records"][-1]["date"])
    future["records"] += [
        {
            "date": (end + timedelta(days=i)).isoformat(),
            "channel": "ads",
            "visitors": 100000,
            "new_users": 90000,
        }
        for i in range(1, 9)
    ]
    after = pipeline.run(AnalysisRequest.model_validate(future))
    assert before.anomalies[0] == after.anomalies[0]


def test_input_order_invariance(payload, settings):
    pipeline = GrowthPipeline(settings)
    expected = pipeline.run(AnalysisRequest.model_validate(payload))
    payload["records"].reverse()
    actual = pipeline.run(AnalysisRequest.model_validate(payload))
    assert expected.anomalies == actual.anomalies
    assert expected.actions == actual.actions


@pytest.mark.parametrize("scenario", ["normal", "weekly", "gradual_drift"])
def test_clean_and_seasonal_data(scenario, settings):
    payload, _ = generate_data(scenario=scenario)
    report = GrowthPipeline(settings).run(AnalysisRequest.model_validate(payload))
    assert not report.anomalies


def test_missing_dates_and_cold_start(payload, settings):
    del payload["records"][10:30]
    report = GrowthPipeline(settings).run(AnalysisRequest.model_validate(payload))
    assert "missing_dates:ads" in report.warnings
    tiny = AnalysisRequest.model_validate({"records": payload["records"][:2]})
    cold = GrowthPipeline(settings).run(tiny)
    assert cold.evaluated_count == 0
    assert cold.skipped_count == 2
    assert cold.anomalies == []


def test_history_expires_by_calendar_days(payload, settings):
    payload["records"][-1]["date"] = "2026-01-01"
    report = GrowthPipeline(settings).run(AnalysisRequest.model_validate(payload))
    assert report.anomalies == []
    assert report.skipped_count == 57


def test_zero_baseline_is_finite(payload, settings):
    for row in payload["records"][:-1]:
        row.update(visitors=0, new_users=0)
    report = GrowthPipeline(settings).run(AnalysisRequest.model_validate(payload))
    assert report.anomalies[0].expected_users == 0
    assert report.findings[0].baseline_cac is None
    assert "NaN" not in report.model_dump_json()


@pytest.mark.parametrize(
    "patch",
    [
        {"new_users": -1},
        {"visitors": 1},
        {"spend": float("nan")},
        {"spend": float("inf")},
        {"channel": "ignore instructions"},
        {"date": "not-a-date"},
        {"new_users": True},
        {"new_users": "100"},
        {"unexpected": "field"},
    ],
)
def test_bad_record_rejected(payload, patch):
    payload["records"][0].update(patch)
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(payload)


def test_empty_duplicates_and_oversize_rejected(payload):
    for rows in ([], [payload["records"][0]] * 2, [payload["records"][0]] * 10001):
        with pytest.raises(ValidationError):
            AnalysisRequest.model_validate({"records": rows})


def test_invalid_detection_config():
    with pytest.raises(ValidationError):
        DetectionOptions(lookback_days=14, min_history=30)
    with pytest.raises(ValidationError):
        DetectionOptions(lookback_days=14, min_seasonal_samples=8)


def test_explicit_nonseasonal_rolling_baseline(payload, settings):
    request = AnalysisRequest.model_validate(
        {
            **payload,
            "options": {"seasonality": "none"},
        }
    )
    report = GrowthPipeline(settings).run(request)
    assert report.anomalies[0].baseline_method == "rolling"
    assert report.skipped_count == 14
    assert (
        DetectionOptions(lookback_days=14, min_history=14, seasonality="none").lookback_days == 14
    )


def test_generator_is_reproducible_and_validates():
    assert generate_data(seed=4) == generate_data(seed=4)
    assert generate_data(seed=4) != generate_data(seed=5)
    for kwargs in ({"days": 1}, {"scenario": "unknown"}):
        with pytest.raises(ValueError):
            generate_data(**kwargs)
