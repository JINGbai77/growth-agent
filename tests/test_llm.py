import json

import httpx
import pytest

from growth_agent.config import Settings
from growth_agent.llm import OllamaReasoner
from growth_agent.service.pipeline import GrowthPipeline


def with_reasoner(settings, handler):
    enabled = settings.model_copy(update={"llm_enabled": True})
    reasoner = OllamaReasoner(enabled, transport=httpx.MockTransport(handler))
    return GrowthPipeline(enabled, reasoner)


def test_offline_never_calls_provider(analysis_request, settings, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline mode contacted an LLM")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    pipeline = GrowthPipeline(settings)
    assert pipeline.run(analysis_request).llm.status == "not_requested"
    request = analysis_request.model_copy(update={"use_llm": True})
    assert pipeline.run(request).llm.status == "disabled"


def test_structured_model_output_with_known_evidence(analysis_request, settings):
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is False
        assert "properties" in body["format"]
        evidence = json.loads(body["messages"][1]["content"])
        content = {
            "summary": "Investigate traffic volume.",
            "advice": [
                {
                    "anomaly_id": evidence["anomalies"][0]["id"],
                    "hypothesis": "Delivery may have changed.",
                    "validation_step": "Compare campaign delivery with control campaigns.",
                }
            ],
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    report = with_reasoner(settings, handler).run(
        analysis_request.model_copy(update={"use_llm": True})
    )
    assert report.llm.status == "ok"
    assert report.llm.content.advice[0].anomaly_id == report.anomalies[0].id
    assert "unverified" in report.llm.disclaimer


@pytest.mark.parametrize(
    "failure", ["timeout", "status", "bad_json", "shape", "unknown_id", "duplicate"]
)
def test_failure_falls_back_without_losing_report(analysis_request, settings, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret provider error", request=request)
        if failure == "status":
            return httpx.Response(503)
        if failure == "bad_json":
            return httpx.Response(200, content=b"invalid")
        if failure == "shape":
            return httpx.Response(200, json={"unexpected": []})
        anomaly_id = (
            "unknown" if failure == "unknown_id" else f"ads:{analysis_request.records[-1].date}"
        )
        item = {"anomaly_id": anomaly_id, "hypothesis": "Unverified", "validation_step": "Check"}
        content = {"summary": "Unverified", "advice": [item] * (2 if failure == "duplicate" else 1)}
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    request = analysis_request.model_copy(update={"use_llm": True})
    report = with_reasoner(settings, handler).run(request)
    assert report.llm.status == "fallback"
    assert len(report.anomalies) == len(report.findings) == len(report.actions) == 1
    assert "secret" not in report.model_dump_json()


def test_no_anomalies_does_not_call_model(analysis_request, settings):
    def handler(request):
        pytest.fail("No evidence to enrich")

    request = analysis_request.model_copy(
        update={"records": analysis_request.records[:-1], "use_llm": True}
    )
    assert with_reasoner(settings, handler).run(request).llm.status == "no_anomalies"


@pytest.mark.parametrize(
    "url", ["ftp://host", "invalid", "https://user:pass@host", "http://host?token=secret"]
)
def test_bad_provider_configuration(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, ollama_url=url)
