class DecisionAgent:
    def decide(self, reasons):
        actions = []

        for r in reasons:
            if "广告" in r:
                actions.append("优化广告素材 + A/B测试")
            elif "自然流量" in r:
                actions.append("加强内容与SEO优化")
            elif "推荐" in r:
                actions.append("优化邀请裂变机制")

        return actions
