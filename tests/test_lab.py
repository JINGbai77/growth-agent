from tests.test_api import wait_for_job


def test_connected_scenarios_budget_experiments(client, payload):
    job_id = client.post("/v1/jobs", json=payload).json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "succeeded"
    report = client.get(f"/v1/jobs/{job_id}/report").json()
    scenario = client.post(
        f"/v1/jobs/{job_id}/scenarios",
        json={
            "anomaly_id": report["anomalies"][0]["id"],
            "recovery_fraction": 0.5,
        },
    )
    assert scenario.status_code == 200
    assert scenario.json()["result"]["scenarios"][0]["modeled_users"] == 700
    assert (
        client.post(
            f"/v1/jobs/{job_id}/scenarios",
            json={
                "anomaly_id": "invented",
                "recovery_fraction": 0.5,
            },
        ).status_code
        == 422
    )

    budget = {
        "total_budget": 1000,
        "quantum": 100,
        "assumption_source": "simulated",
        "channels": [
            {"channel": "ads", "max_incremental_users": 100, "scale_budget": 300, "cap": 1000}
        ],
    }
    assert client.post(f"/v1/jobs/{job_id}/budget", json=budget).status_code == 200
    budget["channels"][0]["channel"] = "unknown"
    assert client.post(f"/v1/jobs/{job_id}/budget", json=budget).status_code == 422

    result = client.post(
        f"/v1/jobs/{job_id}/experiments",
        json={
            "experiments": [
                {
                    "name": "signup",
                    "control_visitors": 10000,
                    "control_conversions": 1000,
                    "treatment_visitors": 10000,
                    "treatment_conversions": 1200,
                    "required_per_arm": 10000,
                    "fixed_horizon_complete": True,
                }
            ]
        },
    )
    assert result.status_code == 200
    artifacts = client.get(f"/v1/jobs/{job_id}/artifacts").json()["artifacts"]
    assert {artifact["kind"] for artifact in artifacts} == {"scenario", "budget", "experiment"}
    assert all(artifact["source_job_id"] == job_id for artifact in artifacts)
    assert all("result" in artifact for artifact in artifacts)

    plan = client.post("/v1/experiments/plan", json={"baseline_rate": 0.1, "absolute_mde": 0.02})
    assert plan.status_code == 200
    assert plan.json()["per_arm_sample_size"] > 3000


def test_dashboard_and_examples(client):
    assert client.get("/").status_code == 200
    examples = client.get("/v1/examples").json()
    assert examples["data_kind"] == "synthetic"
    assert len(examples["analysis"]["records"]) == 252
