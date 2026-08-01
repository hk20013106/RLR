# 未来方向：AI4AI、PaSa 借鉴与 v2.1 MCP 改造

> 合并自：`AI-for-AI与PaSa阅读笔记.md`、`pasa-借鉴与改进方向.md`、`research-loop-v21-mcp-ai4ai-refactor-plan.md`
> 最后更新：2026-07-30
> 状态：方向性文档，不阻塞 v0.9 发布

---

## 一、PaSa 是什么

PaSa（Paper Search Agent，字节跳动）把学术文献检索拆成两个角色：

- **Crawler**：生成搜索词 → 调搜索 API → 读论文 → 追引用链。用 PPO 强化学习训练。
- **Selector**：读标题+摘要，输出 0~1 连续分数（>0.5 = 相关）。SFT 即可。

关键参数：`expand_layers=2`、`search_queries=5`、`threads_num=20`。

资源：
- 论文：https://arxiv.org/abs/2501.10959
- 代码：https://github.com/bytedance/pasa
- 解读：https://mp.weixin.qq.com/s/K2r7AUAWk2DGRwhcjYCuWA

---

## 二、PaSa 对 RLR 最有价值的设计

### 2.1 "找"与"筛"分开

当前 Curie 一个人又搜又筛，prompt 混杂搜索策略和筛选判断。拆开后：
- 搜索质量差 vs 筛选太松，是两个独立问题
- 可以独立优化各自 prompt
- 调试更容易

**对 RLR 的映射：**
```
Curie 的文献任务
  ├─ PaSa Crawler：生成搜索词、搜索、阅读、扩展引用
  ├─ PaSa Selector：初步筛选和排序
  └─ Curie/验证器：核对来源、DOI/PMID、原文和证据，写正式 receipt
```

PaSa **可以**替代 Curie 的"找"和"初筛"，**不能**替代"核验"和"负责"。

### 2.2 引用链扩展

搜到高分论文后，追踪其 references 和 citations 再筛选，递归 1-2 层。
- 当前 Curie L8.5 是一次性搜索，遗漏了关键引用。
- 可用：OpenAlex `referenced_works` / `cited_by`（免费无 key），或 Semantic Scholar `/paper/{id}/references`。

### 2.3 搜索词多样性

把问题改写成 3-5 个互斥搜索词，覆盖同义词、上位概念、方法名、领域术语。
- 当前 pre_research seed queries 多样性不足。
- 短期 fix：prompt 里要求"生成 3-5 个互斥搜索词"。

### 2.4 连续分数

不输出 yes/no，输出 0-10 分，用于排序和引用链扩展优先级。

### 2.5 效率约束

PaSa 奖励设计：`找到高分论文数 × 1.5 - API 调用次数 × 0.1`
- 可简化为 prompt 引导："5 次搜索内覆盖尽可能多相关文献"
- 可在 `preresearch.py` 加 `source_count/query_count` 比率审计

### 2.6 去重

用稳定 ID（arXiv ID / DOI / PMID）记录已处理论文，避免跨轮次重复。

---

## 三、不适用的部分

| PaSa 特性 | 原因 |
|-----------|------|
| arXiv 专用搜索 | 需要 PubMed/EuropePMC |
| Qwen2.5-7B 本地模型 | 用远程 LLM，成本/能力差距 |
| PPO 训练流程 | 需要大量 GPU 和数据，短期不现实 |
| Google Search API | 已有 academic-research-suite skill |

---

## 四、v0.10+ 改进路线图

### P0（下个版本）

- [ ] **引用链追踪**：`academic-research-suite` skill 增加 OpenAlex/Semantic Scholar 引用查询，高分论文自动扩展 1 层
- [ ] **搜索词多样性**：改进 pre_research prompt，要求 3-5 个互斥搜索词

### P1（v0.11）

- [ ] **效率审计**：`preresearch.py` 加 source_count/query_count 比率告警
- [ ] **文献库去重增强**：title-normalized 去重 + 跨轮次防重复
- [ ] **连续评分**：L8.5 筛选改为 0-10 分

### P2（长期）

- [ ] **搜索/筛选职责分离**：DAG 增加独立筛选节点（或 L8.5a 子步骤）
- [ ] **引用链深度可配置**：preflight 允许指定 `expand_layers`（默认 1）
- [ ] **搜索策略反馈循环**：记录每轮效率指标，用于改进后续 prompt

---

## 五、v2.1 MCP 文献管线改造计划

### 5.1 背景与约束

- `literature-search-mcp` 已通过安装、类型检查、39 项测试、真实 Crossref 检索；SHA-256：`C81897B321BBA024CCAF8D8C2030C46D6E3735B758F42D21A64A28C2782FAF46`
- 覆盖 7 个来源的搜索、归一化、去重和 RRF 融合，但**不提供**：全文、章节定位、引用图、完整原始响应
- 现有 MCP 集成文档中"以摘要代替章节证据"和"从归一化结果拼造原始元数据"两项方案**废止**
- 所有新增行为只进入原生 v2.1（L8 Tukey、L8.5 Curie、L9a→L9b 串行），不修改 v2.0

### 5.2 四阶段文献管线

将"一个研究 agent 包办全流程"拆为四个阶段：

1. **QueryPlanner / Curie**：生成版本化查询计划（主题主线、方法、同义词、反证、来源策略、预算）
2. **Crawler / MCP**：执行冻结查询计划，搜索+归一化+强标识符去重+RRF 融合；记录每个来源状态，禁止静默回退
3. **Selector / Curie**：相关性筛选，分别记录入选/拒绝/待人工及理由；RRF 分数与相关性评分、证据质量保持三个独立字段
4. **Evidence Extractor / Verifier**：用 ARS/Curie 获取真实来源元数据、全文和章节；只有该阶段取得的真实响应才能写入 `source_metadata_response`

新增版本化接口：`DiscoveryQueryPlan/v1`、`DiscoveryRunReceipt/v1`、`SelectionReceipt/v1`

发现产物写入 `09_Literature_Database/discovery_runs/<run_id>/`，不冒充 evidence pack。

### 5.3 MCP 工具固化任务

- 源码及 Apache-2.0 LICENSE/NOTICE 纳入 `tools/literature-search-mcp/`，锁定版本和源码哈希
- 增加确定性 CLI：stdin JSON 请求 → stdout JSON 响应，日志进 stderr
- 增加 `history_mode=disabled|path`；Research Loop 正式调用禁用全局历史
- 修复 Windows `test:live` 环境变量语法；启动前检查 Node ≥22 和构建产物

### 5.4 AI4AI 最小治理层

- `OptimizationContract/v1`：目标能力、允许/禁止修改范围、隔离评估集、资源预算、接受规则、停止规则、人工升级条件
- 独立系统优化实验账本：每次干预记录代码/prompt/模型/工具/数据/评估器版本和 accepted/rejected/escalated
- 科学假设账本（已有）管理科学事实；系统优化账本管理软件实验，**两者不得混用**
- 优化者不得修改自己的评估器、门槛或隐藏基准
- 先用于文献检索替换，通过验证后再扩展

### 5.5 上线验收门槛

- 冻结 ≥30 个 v2.1 查询案例（L1/L4/L8.5、反证、重复、预印本、来源故障）
- 切换门槛：标识符/回执/哈希完整率 100%、错误合并 0、伪造元数据 0、Recall@20 非劣界限 ≥−2%、p95 不超旧路径 1.5×
- ≥3 次完整 v2.1 小流量运行后才能设为必经发现层
- MCP 不可用时默认阻断；人工批准旧发现器须创建新 run ID 并记为 escalated

### 5.6 明确禁止

- 不修改 v2.0 的 L9 并行行为
- 不让 v2.0 数据进入 v2.1 运行
- 不用摘要/URL/sentinel 绕过章节定位
- 不伪造 `source_metadata_response`
- 不把 RRF 排名当科学证据质量
- 不让系统优化器修改自己的评估门槛

---

## 六、接入 PaSa 时的保护要求

接入前必须补齐：原始查询、实际搜索词、搜索时间、论文稳定标识（DOI/PMID/arXiv ID）、来源 URL 和内容 hash、PaSa 相关性分数及理由、去重记录、最终 Curie/验证器证据记录。

PaSa 分数只能用于排序，不能绕过 RLR 的 schema、权限、gate 和 ledger 验证。
