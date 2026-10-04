# Task 11 — PaperQA2 cumulative corpus acceptance

日期：2026-10-02（Asia/Shanghai）

**TASK_11=BLOCKED；REAL_E2E=BLOCKED。** 首个真实 blocker 是当前 Codex/继承 worker 环境缺少所需 provider credential。用户明确要求此条件下立即停止；真实 Europe PMC、embedding、summary 和 host acquisition loop 均未启动。本报告不把离线软件回归作为真实科研验收。

## 授权、输入与停止条件

仅执行已批准 [implementation plan 的 Task 11](../docs/superpowers/plans/2026-10-01-l05-paperqa2-cumulative-corpus.md)。[Approved spec](../docs/superpowers/specs/2026-10-01-l05-paperqa2-cumulative-corpus-design.md) SHA-256：`86670dd9c8f83968abe9ce07f9af367fff3117026037ca4c0a1a93c92e9e6b7c`。没有重新设计或实施 Task 1–10。

用户在本轮确认沿用 four-species cardiac RNA-seq，并随后指定：

- 项目：`D:/research_loop/e2e_phase2c_20260925_clean_02/four-species-hhr-rlr`。
- 唯一 runtime binding：[deep_research_runtime.json](D:/research_loop/e2e_phase2c_20260925_clean_02/four-species-hhr-rlr/00_Preflight/deep_research_runtime.json)。
- 允许凭据可用后通过既有 owner 补齐非敏感 corpus 配置；禁止建立第二套 provider 配置。
- 当前 Codex session 是唯一 host cognition；只使用既有 `host-next / host-submit`。
- 首个真实 blocker 停止依赖步骤；SiliconFlow credential 为 MISSING 时立即停止 Task 11，不切换 provider/model，不读取或复制 Hermes secret，不安装依赖。
- 不 commit/push/merge。

上述指定项目未修改，未创建新的真实 acquisition run，未冻结此次 ResearchSeed、worker Task 或 Settings。因此，本报告不把此前另一个 four-species 测试项目的候选身份或科学结论当作本次已冻结输入。

## 首个真实 blocker

**分类：DRIVER / ACCEPTANCE ERROR — required provider credential readiness。** 这是验收前置条件不足，没有产生模型输出，不能归类为 MODEL CONTRACT FAILURE；没有证据指向 PRODUCTION BUG 或 ARCHITECTURE GAP。

通过 canonical worker interpreter `C:/Users/hk200/miniforge3/envs/rlr/python.exe` 启动子进程，检查继承的当前环境中 `SILICONFLOW_API_KEY` / `OPENAI_API_KEY` 是否存在非空值。只输出：

```text
REQUIRED_PROVIDER_CREDENTIAL=MISSING
```

检查退出码 0，命令工具记录耗时 0.952 秒。未打印 key、长度或前后缀；未读取 secret 文件、Hermes secret、用户/系统持久环境 registry，也未尝试复制或重新注入 credential。该结论针对当前 session 与直接继承其环境的 worker，不能推断其他进程或安全存储是否持有凭据。

原始枚举回执：[task11-credential-readiness.log](../.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task11-credential-readiness.log)。

指定 binding 在只读检查时 SHA-256 为 `01afc0b3298f67a21cecadc26aeefcd5ffeb763b9935e74daabc876604749801`；存在 `paperqa2`，未包含 `worker_mode`、`settings`、`timeout_seconds`。按用户要求，credential 为 MISSING 后没有补齐或冻结配置。见 [binding 只读回执](../.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task11-binding-readonly-receipt.json)。

## 请求配置与实际运行记录

以下是用户指定但**未写入 binding / 未冻结 / 未运行**的配置：

| 项目 | 请求值 | 实际情况 |
| --- | --- | --- |
| worker_mode | corpus-evidence-v1 | 未更新旧 binding |
| embedding | st-multi-qa-MiniLM-L6-cos-v1 | 未加载/执行真实 embedding |
| summary profile | siliconflow-deepseek-v3 | 未调用 |
| LiteLLM model | openai/deepseek-ai/DeepSeek-V3 | 未调用 |
| api_base | https://api.siliconflow.com/v1 | 无 API 请求 |
| timeout_seconds | 300 | 未冻结；无 worker 耗时 |
| evidence_k | 60 | 请求预算；无实际 retrieval |
| evidence_retrieval | true | 未冻结 |
| evidence_skip_summary / evidence_text_only_fallback | false / false | 未冻结 |
| use_doc_details / multimodal | false / false | 未冻结 |
| texts_index_mmr_lambda | 1.0 | 未冻结 |
| max_concurrent_requests | 4 | 未冻结 |
| acquisition budget | 每 attempt 最多新增 30、最多 3 次、累计最多 90 | 未执行任何 attempt |

批准配置中的 `embedding_config` / `summary_llm_config`、显式 `parsing.defer_embedding` 和空 `doc_filters` 未在本轮构造或试探；凭据前置条件失败后停止所有配置执行。原始 Scientific question / Hypothesis 未因验收改变，focus/replan 也未生成。

PaperQA2 checkout 只读核实：`D:/research_loop/paper-qa`，HEAD `57e89f7223b0960d5ee5ea048c69e3c47e088572`，`git status --porcelain` 为空。这证明当前源码身份，不证明本次真实 provider 兼容性或模型执行成功。

| 真实阶段 / 指标 | 实际记录 |
| --- | --- |
| Credential readiness | BLOCKED，MISSING |
| Binding update/freeze | NOT ATTEMPTED |
| 新 live acquisition run / attempt | 未创建 / 0 |
| Europe PMC discovery / XML HTTP requests | 0；NOT ATTEMPTED |
| Corpus size | 没有本次 corpus；新增真实论文 0，不把已有历史 corpus 算入 |
| PaperQA2 worker invocation | 0；NOT ATTEMPTED |
| 真实 embedding / summary calls | 0 / 0 |
| 实际 runtime/result/completion | 未产生 |
| worker 耗时、峰值内存、tokens、成本 | N/A；未运行，不填估计值 |
| Source verification | NOT ATTEMPTED |
| Semantic admission | NOT ATTEMPTED |
| Scientific coverage | NOT ATTEMPTED；无 PASS/INSUFFICIENT assessment |
| Host-next / host-submit live cognition | 0 / 0；NOT ATTEMPTED |
| focus / replan | 未产生；NOT ATTEMPTED |
| 失败/恢复 | 凭据 gate 阻塞；没有 live retry、replay 或恢复 |
| EvidencePack / manifest / L1 advance | 未产生 / 未产生 / NOT ATTEMPTED |
| 独立 30/60/90 压力 run | NOT ATTEMPTED |

`REAL_E2E=BLOCKED` 是软件/运行前置条件的状态，不能替代科学 `INSUFFICIENT`。没有提前 scientific PASS，也没有为填满预算制造论文、pagination、replan 或修改 coverage。

## 本轮离线工作及中止处理

在用户进一步指定 credential-first 停止条件前，按 Task 11 Step 1 起草了三个 driver 测试：公开协议调用、NEEDS_HOST 暂停/同请求恢复、首错停止后续阶段。尚未实现 live driver，随后启动计划指定的 red 命令：

```text
PYTHONPATH=src PYTHONNOUSERSITE=1 PYTHONUTF8=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
C:/Users/hk200/miniforge3/envs/rlr/python.exe -m pytest tests/test_l05_curie_corpus_integration.py -q
```

凭据 gate 返回 MISSING 时，该命令仍运行。立即停止本轮拥有的 pytest process tree（root PID 39640），保留 [task11-red.log](../.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task11-red.log)。只有 `FFF................` 进度，没有终端 summary；**collected / passed / failed / skipped 的最终计数均 UNKNOWN，不能称为有效完成的 RED 或 GREEN。** 其中现有测试仍是受控离线 fixture，不是 Europe PMC/真实 summary 验收。

未完成测试草稿保存在 [task11-unimplemented-tests-draft.py](../.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task11-unimplemented-tests-draft.py)，不放入活动测试集。仅撤回本轮起草部分，并以启动时 SHA-256 证明活动 `tests/test_l05_curie_corpus_integration.py` 精确恢复；没有删除或覆盖 Task 1–10 修改。

对本轮 baseline 中 149 个文件逐个比对 SHA-256：全部一致，其中包括全部 `src/**/*.py`、bridge、AGENTS、approved spec/plan 和两份 Task 11 测试/driver 文件。见 [task11-stop-receipt.json](../.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task11-stop-receipt.json)。`git diff --check` 本轮退出 0。

此前 Task 1–10 的 **2,089 collected / 2,088 passed / 0 failed / 1 skipped** 来自 [既有实施报告](../docs/superpowers/2026-10-01-l05-paperqa2-cumulative-corpus-execution-report.md) 的已完成离线回执。本轮没有重跑全回归，不能将该历史结果称为本轮 live green。

| Task 11 计划步骤 | 本轮状态 |
| --- | --- |
| 1. Driver targeted failing tests | 草稿归档；未完成验收 |
| 2. 完整 red 验证 | 中止，无最终计数 |
| 3. 窄 driver/report、targeted green、两个 pinned-native cases | Driver/green/native cases NOT ATTEMPTED；阻塞报告已保存 |
| 4. 真实 case | BLOCKED 于 credential readiness，依赖阶段 NOT ATTEMPTED |
| 5. Readiness evidence/report | 本阻塞报告已核对；Task 11 不标 complete |

## 仍为 NOT VERIFIED 的能力

真实多篇/多轮累计 corpus、真实 provider embedding/summary、evidence_k=60 的 scientific recall、真实最长 paragraph fidelity、source verification、semantic admission、科学 coverage、validated gap focus/replan、真实 NEEDS_HOST pause/replay 且无新增 worker calls、反证/科学 insufficiency、实际故障恢复、最终冻结与消费边界，以及真实 30/60/90 的成本/耗时/内存。

Task 1–10 的离线 gate 没有被此次失败否定，也没有获得新的真实验收证据。架构没有修改；本轮没有新增 controller、provider、serializer、retrieval、reranking、summary 或 relevance 实现。

## 本轮交付与停止

仓库 `D:/research_loop/main`；开始核实的分支 `review/l05-p1-final-diff`，HEAD `c60632afdb3aabd6e7c55ffea8dd6a43c50c7982`，只有原 primary worktree。已有 dirty changes 全部保留。无 commit/push/merge，无依赖安装，无 provider 切换，无 secret 读取/复制。

新增本报告；本计划的 ignored evidence workspace 新增 Task 11 brief、baseline、未完成草稿、原始中断日志和停止/只读回执，ledger 追加本轮状态。生产代码、活动 driver/tests、AGENTS、spec、plan 和指定 runtime binding 均保持原 bytes。

**停止于用户明确要求的 `REQUIRED_PROVIDER_CREDENTIAL=MISSING` gate。** 恢复条件是当前 Codex/worker 环境中指定 SiliconFlow credential 可用；应先重新做只输出 AVAILABLE/MISSING 的 readiness check，再沿同一批准 Task 11 继续。此报告不授权切换模型、补偿性生产 patch 或其他真实 run。
