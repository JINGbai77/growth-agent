import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from growth_agent.experiments import (
    ExperimentBatch,
    ExperimentPlan,
    evaluate_experiments,
    plan_experiment,
)
from growth_agent.models import AnalysisReport
from growth_agent.planning import (
    BudgetRequest,
    ScenarioRequest,
    allocate_budget,
    recovery_scenarios,
)

router = APIRouter(prefix="/v1", tags=["Decision lab"])


def completed_report(request: Request, job_id: UUID) -> AnalysisReport:
    row = request.app.state.store.get(str(job_id))
    if row is None:
        raise HTTPException(404, "Job not found")
    if row["status"] != "succeeded":
        raise HTTPException(409, "A completed report is required")
    return AnalysisReport.model_validate_json(row["report_json"])


def persist(request: Request, job_id: UUID, kind: str, payload, result: dict):
    artifact_id = request.app.state.store.save_artifact(
        str(job_id), kind, payload.model_dump_json(), json.dumps(result)
    )
    return {"artifact_id": artifact_id, "source_job_id": str(job_id), "result": result}


@router.post("/experiments/plan")
def sample_size(payload: ExperimentPlan):
    return plan_experiment(payload)


@router.post("/jobs/{job_id}/scenarios")
def scenarios(job_id: UUID, payload: ScenarioRequest, request: Request):
    report = completed_report(request, job_id)
    anomaly = next((a for a in report.anomalies if a.id == payload.anomaly_id), None)
    if anomaly is None:
        raise HTTPException(422, "anomaly_id must reference the source report")
    if anomaly.direction != "drop":
        raise HTTPException(422, "Recovery scenarios require a drop anomaly")
    result = recovery_scenarios(anomaly, payload.recovery_fraction)
    return persist(request, job_id, "scenario", payload, result)


@router.post("/jobs/{job_id}/budget")
def budget(job_id: UUID, payload: BudgetRequest, request: Request):
    report = completed_report(request, job_id)
    source = request.app.state.store.get(str(job_id))
    observed_channels = {row["channel"] for row in json.loads(source["request_json"])["records"]}
    if not {channel.channel for channel in payload.channels} <= observed_channels:
        raise HTTPException(422, "Budget channels must exist in source data")
    result = allocate_budget(payload)
    result["evidence_run_id"] = report.run_id
    return persist(request, job_id, "budget", payload, result)


@router.post("/jobs/{job_id}/experiments")
def experiments(job_id: UUID, payload: ExperimentBatch, request: Request):
    completed_report(request, job_id)
    return persist(request, job_id, "experiment", payload, evaluate_experiments(payload))


@router.get("/jobs/{job_id}/artifacts")
def list_artifacts(job_id: UUID, request: Request):
    completed_report(request, job_id)
    artifacts = request.app.state.store.list_artifacts(str(job_id))
    for artifact in artifacts:
        artifact["result"] = json.loads(artifact.pop("result_json"))
    return {"artifacts": artifacts}
