from growth_agent.models import Action, Anomaly, Finding

# Versioned knowledge base. Metadata retrieval, not semantic RAG.
PLAYBOOKS = {
    "traffic": (
        "acquisition-volume-v1",
        "Acquisition owner",
        "Audit delivery, channel mix and tracking; compare affected campaigns with controls.",
        "Daily qualified visitors and new users against the same-weekday baseline",
    ),
    "conversion": (
        "signup-funnel-v1",
        "Product analytics owner",
        "Inspect signup steps and recent releases; test a proposed fix with a holdout group.",
        "Visitor-to-signup conversion, with sample size and uncertainty reported",
    ),
    "mixed": (
        "joint-investigation-v1",
        "Growth analyst",
        "Segment by campaign and funnel step; reconcile tracking before choosing an experiment.",
        "New users, traffic and conversion jointly, compared with a control segment",
    ),
}


class DecisionAgent:
    def decide(self, anomalies: list[Anomaly], findings: list[Finding]) -> list[Action]:
        by_id = {a.id: a for a in anomalies}
        actions = []
        for finding in sorted(
            findings, key=lambda f: (-abs(by_id[f.anomaly_id].delta_users), f.anomaly_id)
        ):
            anomaly = by_id[finding.anomaly_id]
            playbook, owner, recommendation, metric = PLAYBOOKS[finding.driver]
            if anomaly.direction == "spike":
                recommendation = (
                    "Validate the increase and exclude duplicate events. " + recommendation
                )
            actions.append(
                Action(
                    id=f"action:{anomaly.id}",
                    anomaly_id=anomaly.id,
                    priority="high" if abs(anomaly.relative_change) >= 0.4 else "medium",
                    playbook_id=playbook,
                    owner=owner,
                    recommendation=recommendation,
                    success_metric=metric,
                    guardrail="No automatic spend changes; monitor CAC and data quality. "
                    "Predefine experiment duration, budget and stopping criteria.",
                )
            )
        return actions
