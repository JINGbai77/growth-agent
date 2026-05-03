class AnomalyAgent:
    def detect(self, data):
        values = [d["new_users"] for d in data]
        avg = sum(values) / len(values)

        anomalies = []
        for d in data:
            if d["new_users"] < avg * 0.7:
                anomalies.append(d)

        return {
            "average": avg,
            "anomalies": anomalies
        }
