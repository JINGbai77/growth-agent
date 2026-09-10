# Portfolio and interview notes

## Credible résumé description (Chinese)

设计并实现 Growth Decision Agent，将渠道增长分析扩展为“异常发现—证据分解—受约束规划—实验验证”的可运行决策支持服务：基于同星期中位数/MAD 构建无未来数据泄漏的分渠道基线，使用 Shapley 双因子分解量化流量与转化率贡献；实现带幂等、限流、故障恢复、历史回放与派生结果追踪的 FastAPI/SQLite 任务系统，并加入反事实情景、凹收益预算优化及含 Wilson 区间、SRM 检查和 Holm 校正的 A/B 实验模块；可选接入本地 Ollama 结构化推理，无模型时保持完整离线能力。通过 74 项测试覆盖边界与故障路径（本地语句覆盖率 97.97%）；在 450 组可复现模拟数据上，检测器取得 0.750 precision / 1.000 recall / 0.857 F1，并明确披露高噪声场景误报及模拟评测边界。

## Short English version

Built an evidence-grounded growth decision service covering anomaly detection, factor attribution,
constrained planning and experiment validation. Implemented leakage-safe seasonal median/MAD
baselines, exact Shapley traffic/conversion decomposition, durable idempotent FastAPI jobs with
lineage, concave budget optimization, guarded A/B inference and optional schema-validated local LLM
reasoning. Added 74 tests (97.97% local statement coverage) and a reproducible 450-dataset synthetic
benchmark reporting 0.750 precision, 1.000 recall and 0.857 F1, with high-noise failure modes and
non-production limits explicitly documented.

## What to discuss in an interview

- Why future-data leakage and mixed-channel baselines make the original detector unreliable.
- Why factor decomposition is evidence, while a cause such as “creative fatigue” is a hypothesis.
- Why the system abstains during seasonal cold start and how this changes latency-to-detection.
- Why the discrete greedy optimizer is optimal only under separable concave gains.
- How SRM, fixed horizons, power and multiple testing prevent premature experiment decisions.
- Why an LLM is downstream of deterministic analysis and why invalid output degrades gracefully.
- How SQLite and a process lease give a credible single-node design, and what changes at scale.

All figures above are directly reproducible. Do not describe them as revenue uplift, production
accuracy, hours saved or completed business experiments.
