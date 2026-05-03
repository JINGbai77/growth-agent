from agents.anomaly import AnomalyAgent
from agents.analysis import AnalysisAgent
from agents.decision import DecisionAgent

class GrowthPipeline:
    def __init__(self):
        self.anomaly = AnomalyAgent()
        self.analysis = AnalysisAgent()
        self.decision = DecisionAgent()

    def run(self, data):
        result = {}

        anomaly_result = self.anomaly.detect(data)
        result["anomaly"] = anomaly_result

        reasons = self.analysis.analyze(anomaly_result["anomalies"])
        result["reasons"] = reasons

        actions = self.decision.decide(reasons)
        result["actions"] = actions

        return result
