import csv
import json
import logging

import pytest

from growth_agent.benchmark import evaluate, latency, metrics
from growth_agent.logging_config import JsonFormatter
from growth_agent.main import load_request, main


def test_cli_generate_analyze_demo_and_bad_file(tmp_path):
    source = tmp_path / "sample.json"
    output = tmp_path / "report.json"
    assert main(["generate", "--output", str(source)]) == 0
    assert source.with_suffix(".labels.json").exists()
    assert main(["analyze", str(source), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["anomalies"]
    assert main(["demo", "--output", str(output)]) == 0
    assert main(["analyze", str(tmp_path / "missing.json")]) == 2


def test_csv_and_large_files(tmp_path, payload):
    source = tmp_path / "sample.csv"
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(payload["records"][0]))
        writer.writeheader()
        writer.writerows(payload["records"])
    assert len(load_request(source).records) == len(payload["records"])
    source.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        load_request(source)


def test_benchmark_reports_labels_and_comparator():
    result = evaluate(seeds=1)
    assert result["datasets"] == 9
    assert result["evaluated_records"] == 9 * (252 - 168)
    assert set(result["detectors"]) == {"robust", "rolling_mean"}
    assert result["detectors"]["robust"]["tp"] > 0
    assert metrics(0, 0, 0)["precision"] is None
    with pytest.raises(ValueError):
        evaluate(seeds=0)


def test_latency_and_cli_benchmark(tmp_path):
    output = tmp_path / "benchmark.json"
    assert main(["benchmark", "--seeds", "1", "--iterations", "1", "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert [r["records"] for r in result["latency"]] == [252, 9999]
    assert "no HTTP/DB/LLM" in result["method"]
    with pytest.raises(ValueError):
        latency(iterations=0)


def test_json_logs_have_context_without_exception_text():
    record = logging.LogRecord("growth_agent", logging.ERROR, "", 0, "job_failed", (), None)
    record.run_id = "test-run"
    record.error_type = "RuntimeError"
    record.secret = "private payload"
    content = JsonFormatter().format(record)
    assert json.loads(content)["run_id"] == "test-run"
    assert "private" not in content
