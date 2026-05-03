class AnalysisAgent:
    def analyze(self, anomalies):
        reasons = []

        for a in anomalies:
            if a["channel"] == "ads":
                reasons.append("广告投放效果下降")
            elif a["channel"] == "organic":
                reasons.append("自然流量下降")
            else:
                reasons.append("推荐链路转化下降")

        return list(set(reasons))
