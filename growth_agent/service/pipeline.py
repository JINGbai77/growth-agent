import logging
from time import perf_counter
from uuid import uuid4

from growth_agent.agents.analysis import AnalysisAgent
from growth_agent.agents.anomaly import AnomalyAgent
from growth_agent.agents.decision import DecisionAgent
from growth_agent.config import Settings
from growth_agent.llm import OllamaReasoner
from growth_agent.models import AnalysisReport, AnalysisRequest, LLMResult

logger = logging.getLogger("growth_agent.pipeline")


class GrowthPipeline:
    def __init__(self, settings: Settings | None = None, reasoner: OllamaReasoner | None = None):
        self.settings = settings or Settings()
        self.anomaly = AnomalyAgent()
        self.analysis = AnalysisAgent()
        self.decision = DecisionAgent()
        self.reasoner = reasoner or OllamaReasoner(self.settings)

    def run(self, request: AnalysisRequest, run_id: str | None = None) -> AnalysisReport:
        run_id = run_id or str(uuid4())
        start = perf_counter()
        timings = {}

        def stage(name, operation):
            before = perf_counter()
            result = operation()
            timings[name] = round((perf_counter() - before) * 1000, 3)
            logger.info(
                "stage_complete",
                extra={"run_id": run_id, "stage": name, "duration_ms": timings[name]},
            )
            return result

        anomalies, evaluated, warnings = stage(
            "detection", lambda: self.anomaly.detect(request.records, request.options)
        )
        findings = stage("analysis", lambda: self.analysis.analyze(anomalies))
        actions = stage("decision", lambda: self.decision.decide(anomalies, findings))
        llm = LLMResult(status="not_requested")
        if request.use_llm:
            if not self.settings.llm_enabled:
                llm = LLMResult(status="disabled", reason="enable_GROWTH_LLM_ENABLED_on_server")
            elif not anomalies:
                llm = LLMResult(status="no_anomalies")
            else:
                llm = stage("llm", lambda: self.reasoner.enrich(anomalies, findings, run_id))
        timings["total"] = round((perf_counter() - start) * 1000, 3)
        return AnalysisReport(
            run_id=run_id,
            record_count=len(request.records),
            evaluated_count=evaluated,
            skipped_count=len(request.records) - evaluated,
            warnings=warnings,
            anomalies=anomalies,
            findings=findings,
            actions=actions,
            llm=llm,
            timings_ms=timings,
        )
