import time
from uuid import uuid4

import pytest


def wait_for_job(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        data = client.get(f"/v1/jobs/{job_id}").json()
        if data["status"] not in {"queued", "running"}:
            return data
        time.sleep(0.01)
    pytest.fail("job did not reach terminal state")


def test_health_docs_and_sync_analysis(client, payload):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200
    assert client.get("/docs").status_code == 200
    assert "/v1/jobs" in client.get("/openapi.json").json()["paths"]
    response = client.post("/v1/analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["run_id"] == response.headers["x-request-id"]
    assert len(response.json()["anomalies"]) == 1


def test_error_envelopes_and_payload_redaction(client, payload):
    payload["records"][0]["channel"] = "secret invalid channel"
    response = client.post("/v1/analyze", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "secret" not in response.text
    assert client.post("/v1/analyze", content="{").status_code == 422
    assert client.get("/missing").json()["error"]["code"] == "http_error"
    assert client.get(f"/v1/jobs/{uuid4()}").status_code == 404
    assert client.get("/v1/jobs/invalid").status_code == 422


def test_streaming_body_limit(client):
    response = client.post("/v1/analyze", content=iter([b"x" * 1048576] * 5))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["x-request-id"]


def test_jobs_persist_idempotency_and_replay(client, payload):
    headers = {"Idempotency-Key": "same-request"}
    first = client.post("/v1/jobs", json=payload, headers=headers)
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    second = client.post("/v1/jobs", json=payload, headers=headers)
    assert second.json()["job_id"] == job_id
    row = wait_for_job(client, job_id)
    assert row["status"] == "succeeded"
    assert "request_json" not in row
    report = client.get(f"/v1/jobs/{job_id}/report").json()
    assert report["run_id"] == job_id
    replay = client.post(f"/v1/jobs/{job_id}/replay").json()
    assert replay["job_id"] != job_id
    assert wait_for_job(client, replay["job_id"])["source_job_id"] == job_id
    replay_report = client.get(f"/v1/jobs/{replay['job_id']}/report").json()
    assert replay_report["anomalies"] == report["anomalies"]
    assert len(client.get("/v1/jobs").json()["jobs"]) == 2
    payload["records"][-1]["new_users"] = 350
    assert client.post("/v1/jobs", json=payload, headers=headers).status_code == 409


def test_unexpected_failure_is_sanitized(client, payload, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("secret database path")

    monkeypatch.setattr(client.app.state.pipeline, "run", broken)
    response = client.post("/v1/analyze", json=payload)
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["error"]["code"] == "internal_error"
    job_id = client.post("/v1/jobs", json=payload).json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "failed"
    assert client.get(f"/v1/jobs/{job_id}/report").status_code == 409


def test_readiness_and_queue_backpressure(client, payload, monkeypatch):
    from growth_agent.service.jobs import QueueFullError

    monkeypatch.setattr(client.app.state.store, "ping", lambda: False)
    assert client.get("/ready").status_code == 503

    def full(*args, **kwargs):
        raise QueueFullError()

    monkeypatch.setattr(client.app.state.jobs, "submit", full)
    response = client.post("/v1/jobs", json=payload)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
