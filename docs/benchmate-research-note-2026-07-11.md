# Benchmate 调研笔记（2026-07-11）

**范围。** 仅审阅 `nataliegits/Benchmate` 仓库的一手资料，固定在 `main` 当时的提交
[`28cfbf7`](https://github.com/nataliegits/Benchmate/tree/28cfbf754eed36f57d33e113393a5eb4636dd963)。以下是代码与仓库文档可证实的结论，不把 README 的性能/成本主张当作独立验证结果。

## 结论先行

Benchmate 值得借鉴的不是“七个 agent”本身，而是它把**候选排序的可靠性**当作一个需要单独验证的对象：顺序消偏的 pairwise judge、可复现的模拟器、领域 gold set、独立模型交叉核对，以及把实验回读做成一次性、确定性的排名修正。对 research loop 来说，优先移植这些治理模式，比复制 LangGraph 外壳更有价值。

它并不能据此被称为“整体上比本项目更完整、更复杂”。仓库自称为 Google Co-Scientist 架构的 *small skeleton*；运行图明确是为清晰而设计的**顺序**执行，生产级并行尚未实现。持久化也只是单个 JSON 文件。因此更准确的定位是：一个在 hypothesis-ranking benchmark 与 UI/证据插件上投入较多的研究原型，而非已具备完整运行审计、工作流恢复和工程测试体系的平台。[README（honesty）](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/README.md#on-honesty) [图执行说明](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/graph.py)

## 架构与执行流

共享状态驱动 7 个角色：Supervisor、Generation、Reflection、Ranking、Evolution、Meta-review、Proximity。Supervisor 根据 `next_action` 路由；任一业务角色完成后都先经过 Proximity，再回到 Supervisor；达到 `max_iterations` 退出。默认 Ranking 节点是公平 judge，只有显式关闭时才回退至单次 LLM 排名。[状态模型](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/state.py) [图 wiring](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/graph.py)

候选以 pairwise Elo 锦标赛排序。调度策略偏向“匹配次数较少、Elo 接近”的候选，同时保留部分跨层比较；公平 judge 对同一对候选按 A/B 与 B/A 各判一次，结果翻转记平局，从而显式抑制位置偏差，而不是把一个 LLM verdict 当作事实。[Elo 调度](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/elo.py) [公平 judge](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/benchmark/fair_judge.py)

## 命令、状态与产物

- CLI 入口是 `python run.py <goal>`，支持 `--resume`、`--max-iterations`、`--n-matches`、`--naive-judge` 与 `--state-file`；另有 Streamlit 前端。CLI 在图完成后将状态写为 JSON，resume 从相同文件恢复。[CLI](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/run.py) [README 使用说明](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/README.md)
- 状态中保留研究目标、计划、候选假设（UUID、Elo、比赛数、review、父代 ID、generation）及 meta-critique；这提供了候选谱系和可续跑基础。[状态定义](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/state.py)
- 证据既可来自运行时 PubMed，也可来自预计算 Geneformer CSV；实验 alamarBlue CSV 被转换为 `data/rig/<hypothesis>_assay.json`。实验结论不仅注入生成/反思 prompt，还以 `(hypothesis, assay)` 标记保证 Elo 加减分只应用一次。[工具与 Geneformer cache](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/tools.py) [assay 处理](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/assay.py) [agent 证据/修正逻辑](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/agents.py)

## 安全、鲁棒性与验证

Ontology grounding 使用短超时、缓存和防御式 JSON 解析；服务不可用时返回空 grounding，而不使锦标赛失败。文档还明确把 grounding 定位为背景信息，术语缺失不能否决新颖机制。[ontology 实现](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/ontology.py) [设计说明](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/README.md#ontology-grounding-for-the-judge)

验证套件围绕真实 Elo 调度提供：免费蒙特卡洛（Spearman、top-k、churn 等）、live judge 的准确率/位置偏差/自一致性诊断、gold-set 端到端验证、fair-vs-naive 与 ontology on/off 对照。仓库的推荐次序是先验证 judge，再用真实 scheduler 扫预算，随后在 gold set 上做端到端验证并至少重复三次。[基准入口](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/benchmark/run_benchmark.py) [完整基准方案](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/benchmark/BENCHMARKING_PLAN.md)

README 还定义了 AlphaGenome、Boltz、Open Targets、DepMap、AlphaMissense 作为彼此独立的定量交叉检查面板：低相关性是人工复核信号，不是自动否决。[交叉检查设计](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/README.md#cross-check-with-other-models-the-panel-of-judges)

## 对 research loop 的可迁移项（按优先级）

1. **为每个选择 gate 建立 benchmark contract。** 用本项目领域的盲标/专家标注集，记录 top-k、重跑稳定性、位置偏差与预算曲线；不要直接复用其 ERAD/multiple-myeloma gold set。
2. **将关键 LLM 比较做顺序交换并定义不一致处置。** A/B 与 B/A 翻转时可标为“不确定、需额外证据”，而非强行产出排序。
3. **让实验/分析回读成为幂等、可审计的状态变更。** 保存原始输入、派生证据、作用方向和 `applied` 标记；在此基础上增加 run ID、输入/模型/prompt/检索快照与 step-level checkpoint，补足 Benchmate 单一 `state.json` 的不足。
4. **独立交叉验证只作警报器。** 将外部定量分数与主排序的分歧排入复核队列，避免把某一模型或 ontology 的缺失误当反证。
5. **保持 fail-soft 的证据接入。** 对外部服务设定超时、结构校验和降级路径，但把降级事件写入审计记录；Benchmate 具备前半部分，审计可由 research loop 补强。

## 不宜照搬的部分

`proximity` 目前只提示重复而不实际去重，`embed()` 是 SHA-256 hash placeholder；graph 注释也确认没有生产级并行。加上单文件非原子持久化、没有完整的 run provenance/输入快照，以及仓库树中未见常规测试工作流，这些都不应视为可直接复用的生产能力。[proximity/embedding](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/tools.py) [顺序图执行](https://github.com/nataliegits/Benchmate/blob/28cfbf754eed36f57d33e113393a5eb4636dd963/co_scientist/graph.py) [工作流目录](https://github.com/nataliegits/Benchmate/tree/28cfbf754eed36f57d33e113393a5eb4636dd963/.github/workflows)

