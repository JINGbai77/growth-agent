from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GrowthRecord(Contract):
    date: date
    channel: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    visitors: int = Field(ge=0, le=10**9, strict=True)
    new_users: int = Field(ge=0, le=10**9, strict=True)
    spend: float = Field(default=0, ge=0, le=10**12)

    @model_validator(mode="after")
    def valid_funnel(self):
        if self.new_users > self.visitors:
            raise ValueError("new_users cannot exceed visitors")
        return self


class DetectionOptions(Contract):
    lookback_days: int = Field(default=56, ge=14, le=365)
    min_history: int = Field(default=14, ge=7, le=60)
    seasonality: Literal["weekday", "none"] = "weekday"
    min_seasonal_samples: int = Field(default=8, ge=4, le=12)
    z_threshold: float = Field(default=3.5, ge=1, le=10)
    min_relative_change: float = Field(default=0.2, ge=0.01, le=1)
    min_absolute_change: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def enough_window(self):
        if self.min_history > self.lookback_days:
            raise ValueError("min_history must not exceed lookback_days")
        if self.seasonality == "weekday" and self.min_seasonal_samples * 7 > self.lookback_days:
            raise ValueError("lookback_days cannot hold the requested seasonal samples")
        return self


class AnalysisRequest(Contract):
    records: list[GrowthRecord] = Field(min_length=1, max_length=10000)
    options: DetectionOptions = Field(default_factory=DetectionOptions)
    use_llm: bool = False

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [(r.date, r.channel) for r in self.records]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate (date, channel) rows; aggregate before submitting")
        return self


class Anomaly(Contract):
    id: str
    date: date
    channel: str
    direction: Literal["drop", "spike"]
    observed_users: int
    expected_users: float
    delta_users: float
    relative_change: float
    robust_z: float
    baseline_method: Literal["same_weekday", "rolling"]
    baseline_samples: int
    baseline_visitors: float
    baseline_conversion: float
    observed_visitors: int
    observed_conversion: float
    observed_spend: float
    baseline_spend: float


class Finding(Contract):
    anomaly_id: str
    driver: Literal["traffic", "conversion", "mixed"]
    traffic_contribution: float
    conversion_contribution: float
    baseline_cac: float | None
    observed_cac: float | None
    evidence: list[str]
    hypotheses: list[str]
    caveat: str = "Arithmetic attribution is not proof of causality; verify with experiments."


class Action(Contract):
    id: str
    anomaly_id: str
    priority: Literal["high", "medium"]
    playbook_id: str
    owner: str
    recommendation: str
    success_metric: str
    guardrail: str
    requires_human_approval: bool = True


class LLMAdvice(Contract):
    anomaly_id: str
    hypothesis: str = Field(min_length=1, max_length=1000)
    validation_step: str = Field(min_length=1, max_length=1000)


class LLMContent(Contract):
    summary: str = Field(min_length=1, max_length=2000)
    advice: list[LLMAdvice] = Field(min_length=1, max_length=10)


class LLMResult(Contract):
    status: Literal["not_requested", "disabled", "no_anomalies", "ok", "fallback"]
    reason: str | None = None
    content: LLMContent | None = None
    disclaimer: str = "Model-generated hypotheses are unverified; review before use."


class AnalysisReport(Contract):
    schema_version: str = "1.0"
    run_id: str
    record_count: int
    evaluated_count: int
    skipped_count: int
    warnings: list[str]
    anomalies: list[Anomaly]
    findings: list[Finding]
    actions: list[Action]
    llm: LLMResult
    timings_ms: dict[str, float]
