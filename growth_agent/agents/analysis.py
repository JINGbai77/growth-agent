from growth_agent.models import Anomaly, Finding


class AnalysisAgent:
    """Symmetric two-factor (Shapley) decomposition of U = visitors * conversion."""

    def analyze(self, anomalies: list[Anomaly]) -> list[Finding]:
        findings = []
        for a in anomalies:
            traffic = (
                (a.observed_visitors - a.baseline_visitors)
                * (a.observed_conversion + a.baseline_conversion)
                / 2
            )
            conversion = (
                (a.observed_conversion - a.baseline_conversion)
                * (a.observed_visitors + a.baseline_visitors)
                / 2
            )
            total = abs(traffic) + abs(conversion)
            driver = "mixed"
            if total and abs(traffic) / total >= 0.7:
                driver = "traffic"
            elif total and abs(conversion) / total >= 0.7:
                driver = "conversion"
            hypotheses = {
                "traffic": [
                    "Check acquisition volume, channel delivery and tracking completeness."
                ],
                "conversion": ["Check signup funnel releases, audience mix and event definitions."],
                "mixed": ["Check both acquisition mix and signup funnel; effects may offset."],
            }
            findings.append(
                Finding(
                    anomaly_id=a.id,
                    driver=driver,
                    traffic_contribution=traffic,
                    conversion_contribution=conversion,
                    baseline_cac=a.baseline_spend / a.expected_users if a.expected_users else None,
                    observed_cac=a.observed_spend / a.observed_users if a.observed_users else None,
                    evidence=[
                        f"New users: {a.observed_users} vs baseline {a.expected_users:.2f}",
                        f"Visitors: {a.observed_visitors} vs baseline {a.baseline_visitors:.2f}",
                        f"Conversion: {a.observed_conversion:.4f} vs {a.baseline_conversion:.4f}",
                        f"Traffic contribution {traffic:.2f} + conversion contribution "
                        f"{conversion:.2f} = user delta {a.delta_users:.2f}",
                    ],
                    hypotheses=hypotheses[driver],
                )
            )
        return findings
