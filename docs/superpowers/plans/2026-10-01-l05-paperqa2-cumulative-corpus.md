# RLR Local PaperQA2 Cumulative Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 native v2.1 L0.5 acquisition owner 内接入本地 PaperQA2 累计语料 evidence worker，使来源、semantic admission、科学 coverage 和恢复均可追溯。

**Architecture:** RLR 保留 discovery/replan、原始 XML、canonical location、验证、持久化和决策权威；PaperQA2 原生 Docs.aadd_texts / aget_evidence 执行完整 embedding、retrieval、summary 和 relevance。扩展既有 controller、bridge、checkpoint、manifest 和 native binding，不建立第二个 acquisition 循环、parser、vector store 或 recovery engine。

**Tech Stack:** Python、现有 RLR contracts/host handoff/ProcessRunner/immutable writers、Europe PMC JATS XML、固定本地 paper-qa 2026.8.12、pytest；Windows/PowerShell。

**Spec:** [Architecture spec 1.1](../specs/2026-10-01-l05-paperqa2-cumulative-corpus-design.md)，SHA-256 86670dd9c8f83968abe9ce07f9af367fff3117026037ca4c0a1a93c92e9e6b7c。

状态：**APPROVED**，版本 1.0，2026-10-01。用户已明确批准 architecture spec 和本 implementation plan，并要求实施前仅做三项最小文档修订。当前授权到修订、self-review 和文档验证为止，随后停止，不开始 Task 1；spec 改变时先同步计划/hash。本文件不授权生产代码修改、真实检索/模型调用、安装、commit/push 或创建 worktree。

## Global Constraints

- USE EXISTING SYSTEM DIRECTLY > ADAPT ITS BOUNDARY > REUSE ITS COMPONENTS > EXTEND/REFACTOR RLR > CREATE。沿用 [现有 reuse audit](../../architecture/external-reuse/2026-10-01-l05-paperqa2-cumulative-corpus-design.json) 的 ADAPT 结论；实施时按实际文件/接口更新该 audit，并运行现有 gate。
- RLR 基线 HEAD c60632afdb3aabd6e7c55ffea8dd6a43c50c7982，仓库 D:/research_loop/main；开始实施时重验 HEAD/worktree/dirty diff，不覆盖现有改动。
- PaperQA2 HEAD 57e89f7223b0960d5ee5ea048c69e3c47e088572，tag v2026.08.12，包版本 2026.8.12。计划轮核实 HEAD/clean status，版本要求来自 spec，本轮未运行 import/模型。
- 仅显式 worker_mode = corpus-evidence-v1 的 native v2.1 新 run；execution_mode 仍为 agent_native。
- max_acquisition_attempts 默认 3、允许 1–3；new_papers_per_attempt 默认/硬上限 30；cumulative_paper_limit 默认/硬上限 90。预算可降低；后续 worker 必须有新增成功 source，最多三次 invocation。
- evidence_k 默认 60、可配置正整数，是 Text 检索预算，不保证逐篇审阅。60 是已批准、尚未实际验收的资源默认值，不承诺 scientific recall。
- discovery page_size = 25，不新增自动 pagination；timeout_seconds 复用 binding 显式正数，不自动延长。
- answer.evidence_retrieval = true；evidence_skip_summary = false；evidence_text_only_fallback = false。
- parsing.use_doc_details = false；multimodal = false；doc_filters 为空；texts_index_mmr_lambda = 1.0；max_concurrent_requests = 4，可显式降低至正整数，不高于 4；显式冻结 parsing.defer_embedding。
- 每 attempt 新建进程内 Docs/session，仅一次 aget_evidence；禁止 aquery、agent/search、bridge 重复 manual retrieval/MMR、隐式加载 PQA_HOME 历史 corpus。
- parser_profile = jats-paragraphs/v2；完整 paragraph，不截断、不跨段拼接、不丢非法 Unicode、不按 Methods/R/D/C 筛选。
- Doc.dockey = canonical paper_id；Doc.docname = canonical paper_id；Doc.citation = title；Text.source_locator 和 Text.section 原样承载既有 RLR location/section，不解析 Text.name、不另建 locator。
- 永久 base claim 精确为 `Scientific question:\n{seed.scientific_question}\n\nHypothesis to evaluate:\n{seed.hypothesis_seed}`；首轮 evidence_focus=null，后续只可 null 或当前 validated/persisted/request-bound gaps 的完整投影。Focus 不改变 claim、hypothesis 或 coverage authority。
- Canonical JSON：UTF-8、ensure_ascii=False、键排序、紧凑 separators、禁止 NaN/Infinity/重复 key、数组有序。重复 key 必须在 raw JSON strict decoder/transport boundary、形成 dict 前拒绝；dict 纯 validator 不宣称能恢复该信息。沿用 acquisition artifact 的单个末尾 LF，文件 SHA 与实际写入 bytes 一致；question 内的 gaps JSON 不附文件末尾 LF，不增加第二套 serializer。
- PaperQA2CorpusTask/v1、PaperQA2CorpusResult/v1；新 checkpoint v2、acquisition manifest v3、result v2；first owner/execution mode v1 和既有 extract/semantic/query/coverage/pack wire 版本保持。
- 首轮所有 attempts 的 round_index = 1、最终 EvidencePack version = 1；attempt_index 不能充当 pack version。
- generate → validate → persist → receipt/hash → advance；未知外部结果 BLOCKED；软件/服务/contract/persistence 错误不能成为科学 insufficiency 或 fallback。
- Legacy PDF/document/L4 显式契约保持；历史 frozen 数据按原 schema 读验，旧未完成 checkpoint 不隐式升级；不改 L4/L8.5/DAG/候选状态权限。
- 每 task 是审核边界。AGENTS.md 禁止未经请求 commit，本计划不安排自动提交；以 diff 和验证回执交付审核。

## Review Focus

1. Windows 路径别名、junction/symlink、TOCTOU：project 内合法路径才可读，dispatch 前重验 bytes/hash；逃逸/替换阻断。Task 1、4、5。
2. 超长段落、同文不同节点、非法编码：完整保留合法正文，lone surrogate 不省略成空结果。Task 2、4、5。
3. 精确预算边界与 bool 冒充 int：30/90/attempt 3、score/k/concurrency 严格检查；预算用尽仍可凭合法 evidence PASS。Task 1、3、8。
4. 落盘与 pointer 之间重启：完整 completion 可恢复，partial result 不证明完成；旧 focus 不被后来 gaps 替换。Task 6、9。
5. 历史 frozen 与新未完成 run 共存：显式 version/owner 分派，缺新 provenance 不退回 legacy，L4/旧命令保持原行为。Task 9、10。

---

## 文件与 owner 地图

生产模块均扩展现有 owner；新文件仅为测试/验收材料。行号为当前 checkout 提示，函数名是修改锚点。

| 文件 | 责任与修改锚点 | Task |
| --- | --- | --- |
| src/research_loop/l05_curie/paperqa2.py | 唯一 corpus Task/Result 纯 validator | 1 |
| src/research_loop/l05_curie/contracts.py | scientific coverage validator、judge_coverage 的 acquisition_state | 1、8 |
| src/research_loop/l05_curie/paperqa2_runtime.py | deterministic question/task、Settings、现有 backend 的 corpus 方法、完整 process capture/completion | 1、4、5 |
| scripts/paperqa2_rlr_bridge.py | schema dispatch、原生 Doc/Text/Docs、task-scoped diagnostics；旧分支保持 | 4 |
| src/research_loop/l05_curie/europepmc.py | 同一 parser/profile、snapshot retriever、独立 verifier 与局部 mismatch 分类 | 2、7 |
| src/research_loop/l05_curie/multisource.py | 复用 dedupe/stable aliases，跨轮冻结身份匹配 | 3 |
| src/research_loop/l05_curie/selector.py | 复用资格/来源记录的 mechanical allocation，不使用 scientific score | 3 |
| src/research_loop/l05_curie/europepmc_runtime.py | 唯一 lifecycle：cumulative refs、HTTP/worker replay、host semantic/coverage、manifest/freeze | 3、6–9 |
| src/research_loop/l05_native_binding.py | native L1 消费边界重验新 acquisition provenance | 9 |
| src/research_loop/deep_research.py、src/research_loop/commands/lifecycle.py、src/research_loop/runtime_preflight.py | 唯一配置读写/可选 capability；L4 binding 行为保持 | 10 |
| src/run_loop.py | host_protocol_submit 的 coverage stage 分派，复用 next/submit/result validator | 10 |
| docs/architecture/external-reuse/2026-10-01-l05-paperqa2-cumulative-corpus-design.json | 实施阶段刷新实际复用证据，不创建第二格式 | 1、10 |
| docs/AGENT_NATIVE_RUN.md、docs/AGENT_CONTEXT.md、README.md | mode/legacy/readiness/恢复操作说明 | 10 |
| tests/test_l05_curie_corpus_contracts.py、tests/test_l05_curie_corpus_allocation.py、tests/test_paperqa2_corpus_bridge.py、tests/test_l05_curie_corpus_process.py | 新增聚焦契约/allocation/bridge/process 行为测试 | 1、3–5 |
| tests/test_l05_curie_corpus_replay.py、tests/test_l05_curie_corpus_semantics.py、tests/test_l05_curie_scientific_coverage.py、tests/test_l05_curie_corpus_integration.py | 新增事务、admission、coverage 和消费验证 | 6–9 |
| tests/paperqa2_corpus_acceptance.py | test-only pinned-native/真实验收 driver，读取现有 binding | 4、11 |
| tests/native_curie_test_support.py 及各 task 的现有 tests | 扩展 strict native fixtures，复用 ledger/候选 bootstrap | 对应 task |

process_runner.py、host_handoff.py、semantic_verifier.py、store.py、research_seed.py、query_planner.py 的现有能力直接调用。没有证据支持新增通用 process runner、callback registry、semantic policy、pack writer、planner 或 recovery subsystem。若实施发现必须修改这些 owner，先证明必要性、更新该 task 的 audit/diff，不在 caller 绕过。

## 验证约定与依赖

后续实施从真实 RLR repo root 运行：

```powershell
$rlrPython = 'C:/Users/hk200/miniforge3/envs/rlr/python.exe'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
```

上述命令在本计划轮未执行。Task 1→2→3→4→5→6→7→8→9→10→11 顺序实施，前置失败停止依赖项。每个 red 必须因缺计划行为而失败，环境/import/fixture failure 不算有效 red。每个 green 记录实际 collected/pass/fail/skip，skip 不满足该行为。每 task 最后审查 diff、重复逻辑和直接相关回执，不自动 commit。

新测试复用 tests/native_curie_test_support.py 的 strict native 项目/ledger 构造，不复刻 bootstrap。测试 fixtures 仅证明软件行为，不称为科学证据。函数签名中返回 dict 的 keys 在 Interfaces 中固定；规范性 wire 详情以 hash-bound spec 为准，避免复制第二契约。

## Task 1: 冻结 worker / coverage 契约、Settings 与 question 身份

**Files:**
- Modify: src/research_loop/l05_curie/paperqa2.py、paperqa2_runtime.py（现有 runtime pin/config 边界）。
- Modify: src/research_loop/l05_curie/contracts.py:64（gap validator）；路由实现留 Task 8。
- Modify: 上表现有 reuse audit，仅实施阶段更新。
- Create: tests/test_l05_curie_corpus_contracts.py。

**Interfaces:**
- paperqa2.py：canonical_corpus_bytes(value: object) -> bytes。
- validate_paperqa2_corpus_task(task: dict, *, acquisition_run_id: str, attempt_index: int) -> dict。
- validate_paperqa2_corpus_result(result: dict, *, task: dict, settings: dict, expected_runtime: dict) -> dict。以上为唯一 RLR 纯 validator，无 I/O，返回 validated 深复制；只检测 dict 中仍可观察的契约条件，重复 JSON key 由 Task 4/5 的 raw transport strict decode 在形成 dict 前拒绝。
- paperqa2_runtime.py：materialize_corpus_question(seed: dict, *, evidence_focus: dict | None) -> str；build_corpus_task(*, acquisition_run_id: str, attempt_index: int, seed: dict, settings_sha256: str, corpus: list[dict], evidence_k: int, evidence_focus: dict | None) -> dict；validate_corpus_worker_config(config: dict) -> dict。
- contracts.py：validate_scientific_coverage_assessment(assessment: dict, *, request_sha256: str, admitted_evidence_ids: list[str]) -> dict；request 文件/receipt provenance 属于 acquisition owner，不放入纯 validator。
- Task identity 定为 PQA_ + SHA-256(canonical bytes of {acquisition_run_id, attempt_index, task: 完整 task 去掉 task_id}) 的前 24 hex；完整 task 文件 SHA 单独计算。短 ID 冲突且 bytes 不同必须 fail closed。run/attempt 来自 owner，不新增 Task wire 字段。

- [ ] **Step 1: 写失败测试。** test_question_focus_changes_task_identity_not_claim：首轮 focus is None/question 精确等于 base；attempt 2 非 null 只追加固定后缀，gap_id 升序且 search_directions 原序；改 focus/coverage binding 改 task_id/hash，base claim hash 不变。test_task_rejects_missing_focus_and_noncanonical_projection：缺 focus、空 gaps、extra/authority 字段、重复 paper/locator、非法 Unicode、NaN/Infinity 均拒绝；重复 JSON key 的 raw 输入测试移至 Task 4/5，不交给 dict validator。test_result_rejects_authority_runtime_count_and_score_mismatch：unknown paper、task/settings/runtime/count 错配、score True/-1/0/11、超过 k 拒绝；合法 empty evidence 接受。test_settings_budget_and_path_boundaries：30/90/1–3、bool、concurrency 1–4/k/timeout 与 flags/default 精确检查。

核心断言（task1/task2/seed/focus 为本文件测试内的合法 wire fixtures，不定义新的生产类型）：

```python
base = materialize_corpus_question(seed, evidence_focus=None)
assert task1["evidence_focus"] is None
assert task1["question"] == base
assert task2["question"] == base + "\n\nEvidence focus:\n" + json.dumps(
    focus["gaps"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
)
assert task1["task_id"] != task2["task_id"]
assert materialize_corpus_question(seed, evidence_focus=None) == base
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_contracts.py -q`；预期新接口/行为 FAIL。
- [ ] **Step 3: 实现上述纯接口。** 字段精确按 spec §6；source locator/text fidelity 留 SourceVerifier。原生 Settings 层级 embedding、summary_llm、answer、parsing、texts_index_mmr_lambda；显式模型及非敏感配置，不写 credentials。focus 只有两个 hash 和全部 gaps，shape 在此验、Task 6 验实际来源；question 后缀精确为 `\n\nEvidence focus:\n{canonical_json(evidence_focus.gaps)}`。canonical_corpus_bytes 复用既有 canonical serializer，保持旧 artifact bytes；raw strict decode 留 Task 4/5 既有 transport owner，不放入接受 dict 的纯 validator、不新增 serializer。task identity 同时绑定 null/focus 与 question。覆盖 project-relative path shape；实际 containment/re读留 Task 4/5。coverage validator 复用 gap owner，验证恰好两维度、唯一 gap、true 至少一条合法 evidence ref、false 对应 gap、空 admitted 不可充分。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_contracts.py tests/test_l05_curie_contracts.py tests/test_l05_curie_paperqa2.py tests/test_l05_curie_paperqa2_runtime.py -q`；预期 PASS。validate 现有 reuse audit 要求 valid=true；审查 task diff。

## Task 2: 在原 JATS owner 扩展全 paragraph profile 和定位

**Files:**
- Modify: src/research_loop/l05_curie/europepmc.py:356（parser）、:386（legacy target filter）、:426（retrieve）、:536（verifier）。
- Modify tests: tests/test_l05_curie_europepmc_evidence.py、tests/test_l05_curie_source_verifier.py。

**Interfaces:**
- parse_jats_paragraphs(raw: bytes, *, parser_profile: str = "jats-paragraphs/v1") -> list[dict]，保持 {section,text,locator} 结构；v1 默认保持旧行为，v2 按 spec §5.3。
- EuropePmcEvidenceRetriever.retrieve(paper: dict, *, seed: dict, parser_profile: str = "jats-paragraphs/v1") -> dict，返回现有 snapshot/candidates；v2 无合法 paragraph 明确 NO_USABLE_PARAGRAPHS，不复用 NO_TARGET_SECTIONS 描述。
- verify_jats_candidates(raw: bytes, candidates: list[dict], *, paper_id: str, role_override: str = "", retrieval_base: dict | None = None, parser_profile: str = "jats-paragraphs/v1") -> list[dict]。
- EuropePmcEvidenceVerifier.verify(snapshot: dict, candidates: list[dict], *, parser_profile: str = "jats-paragraphs/v1") -> list[dict]，独立重读 snapshot。
- JatsSourceMismatchError(CurieContractError)：仅合法已知 proposal 的 unresolved locator/text/section mismatch；XML/profile/path/hash/identity 失败仍 contract/integrity，不广泛 catch。

- [ ] **Step 1: 写失败测试。** test_v2_reads_abstract_methods_captions_unsectioned_body、test_v2_nested_node_once_deepest_locator、test_v2_identical_text_at_distinct_nodes_survives：assert 精确 document-order locator/section/text，空 p 不令后续 ordinal 重排；test_v1_ancestor_locator_still_verifies。test_long_paragraph_not_truncated_and_invalid_encoding_rejected：完整长 text 相等，无替换/省略；非法编码/malformed XML 阻断。

```python
# XML fixture: body/sec A 包含 p="same" 和内嵌 sec B/p="same"。
units = parse_jats_paragraphs(xml, parser_profile="jats-paragraphs/v2")
assert [u["locator"] for u in units] == ["sec:1/p:1", "sec:2/p:1"]
assert [u["text"] for u in units] == ["same", "same"]
assert [u["section"] for u in units] == ["A", "B"]
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_europepmc_evidence.py tests/test_l05_curie_source_verifier.py -q`；仅新 v2 行为失败。
- [ ] **Step 3: 扩展同一 parser/locator map。** 以节点身份、最深 ancestor 和完整 snapshot ordinal 产生 canonical source units；不同节点即使同文均保留。旧 sec:<index>/p:<index> 继续可验证，v2 输入只发 canonical deepest locator；无 sec 使用 spec 的两个 jats:v2 命名空间，不让旧 alias map 成为第二套 Text 输入。复用 normalization/snapshot bytes/hash；reference/作者/附件/tablecells/公式的限制进入 coverage scope。实际 XML parser 宣告的合法源编码仍由原始 bytes解析，生成文本/transport严格 UTF-8；不强制把合法非 UTF-8 XML 原件改写成 UTF-8。独立 verifier 只按明确 mismatch 类型拒绝 proposal。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_europepmc_evidence.py tests/test_l05_curie_source_verifier.py tests/test_l4b_closed_corpus_fulltext.py tests/test_l4b_paperqa2_evidence_wiring.py tests/test_l05_curie_paperqa2_runtime.py -q`；预期 PASS，证明 legacy/L4 默认 profile 未变。

## Task 3: 机械 allocation、跨轮 alias 与 cumulative corpus

**Files:**
- Modify: src/research_loop/l05_curie/selector.py:139、multisource.py:349,481、europepmc_runtime.py:598,1520。
- Create: tests/test_l05_curie_corpus_allocation.py。
- Reuse tests: tests/test_l05_curie_provider_alias_identity.py、tests/test_l05_curie_canonical_identity_integration.py、tests/test_l05_curie_selector.py。

**Interfaces:**
- multisource.py：match_existing_corpus_record(record: dict, *, existing_papers: list[dict]) -> dict | None；复用稳定 ID/aliases，命中返回 frozen paper，冲突抛 CurieContractError，不重算旧 paper_id。
- selector.py：allocate_corpus_candidates(discovery: dict, *, query_plan: dict, existing_papers: list[dict], failed_aliases: list[dict], max_new_papers: int, eligibility: Callable) -> dict，返回 {selected,reserves,excluded,provenance}；有序 canonical records 引用，不伪造旧科学评分 decision。
- europepmc_runtime.py：_extend_corpus(previous: list[dict], additions: list[dict], *, new_limit: int, cumulative_limit: int) -> list[dict]；entry 引用 frozen paper/origin attempt/snapshot path/hash/source units，append-only。_prepare_europepmc_acquisition 新 mode 使用机械 allocator。

- [ ] **Step 1: 写失败测试。** test_round_robin_preserves_query_provider_order：Q1=[A,B], Q2=[C,A,D] → A,C,B,D，A 一次且全部 query provenance 保留。test_alias_enrichment_keeps_id_and_skips_refetch：新 DOI/旧 PMID-PMCID alias 命中、旧 snapshot refs/ID不变、HTTP count=0；同 alias 多 frozen ID / 同 ID 不同 snapshot BLOCKED。test_limits_30_new_90_total：已有70最多加20、发现不足不补造、只有旧来源则selected=[]。test_failed_aliases_and_finite_reserve：404/410/无 paragraph 留失败、有限补位，后续不再抓同失败 alias。

```python
assert [p["paper_id"] for p in allocation["selected"]] == ["A", "C", "B", "D"]
assert len(additions) == 20  # fixture: 70 old papers, 40 eligible new, limit 90
assert cumulative[:70] == previous
assert len(cumulative) == 90
assert http_calls_for_existing_alias == 0
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_allocation.py -q`。
- [ ] **Step 3: 实现窄接口并接 preparation。** dedupe 前保留 raw batch order，以既有 source_records/aliases 映射 canonical merged records，按 QueryPlan round-robin；不依赖 dedupe 的 paper_id 全局排序。eligibility 仍 OA/PMCID/XML/source-type，成功 snapshot 才算新增预算；新 path 不调用 scientific scorer/_ranking，用 raises sentinel 测试。v2 retriever生成完整 units；获取前排除旧/失败 aliases。服务/身份/malformed XML 不以 reserve 隐藏，保持现有具体 resource classifier；有限发现集合耗尽结束。旧 HTTP receipts 保留 origin，不冒充本轮成果。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_allocation.py tests/test_l05_curie_provider_alias_identity.py tests/test_l05_curie_canonical_identity_integration.py tests/test_l05_curie_selector.py -q`；预期 PASS，重复 allocation/extend 得相同 bytes/order。

## Task 4: Bridge 复用原生 Docs，并闭合 terminal diagnostics

**Files:**
- Modify: scripts/paperqa2_rlr_bridge.py:48,146。
- Create: tests/test_paperqa2_corpus_bridge.py、tests/paperqa2_corpus_acceptance.py（此 task 只做 offline native cases）。
- Reuse: tests/test_paperqa2_bridge_transport.py。

**Interfaces:**
- 保留 async _run(request: dict) -> dict 做显式 dispatch；新增 async _run_corpus(request: dict) -> dict。
- 新 stdin envelope 为 {worker_mode,task,settings,project_root,paperqa_repo,pqa_home}，以 task.schema_version=PaperQA2CorpusTask/v1 分派；unknown mode/schema 拒绝，旧 PDF/document 分支行为保持。corpus raw stdin 在既有 transport decoder 形成 dict 前检查所有层级的重复 JSON key 和 NaN/Infinity；拒绝后不调用 _run_corpus/native API。bridge只做必要输入防护，不导入 RLR 包/复制其 authoritative validator，不新增 serializer。
- _CorpusDiagnostics(logging.Handler)::emit(record: logging.LogRecord) -> None：task scoped，记录 capture established/failed 和真实 terminal LLMContextError 数；finally 移除。
- stdout 成功时只一个 canonical Result JSON；失败不返回成功 result。stderr finally 输出一个内部 frame：{paperqa2_corpus_diagnostic:{task_id,capture_established,capture_failed,terminal_context_error_count}}；其他 stderr 是日志。frame 不新增通用 failure schema/registry；缺失/重复/错 task/坏 count/handler失败一律 capability/contract failure。Task 5 从完整 log 解析，与 Result count 一致核验。
- Test-only driver main(argv: list[str] | None = None) -> int；参数 --case native-identity|native-diagnostics|live-corpus、--binding-file 既有 deep_research_runtime.json。offline cases 用 fixed native API和可控 model adapter，不连真实模型、不 patch upstream map_fxn_summary。

- [ ] **Step 1: 写失败测试。** test_native_source_identity_survives_context：Doc.dockey/docname canonical ID，Text.source_locator/section 原样，随机 Text.name 不影响 output；Context 原文而非 summary 返回。test_one_native_aget_evidence_no_manual_pipeline：每 paper aadd_texts、仅一次 aget_evidence、bridge无显式 manual retrieval/MMR/aquery/search。test_empty_context_vs_terminal_failure：正常score0、partialcontexts+终止错误、capturefailure、aadd_texts=False、数量错配、lone surrogate、conflictingduplicate各有不同结果。test_raw_stdin_rejects_duplicate_json_keys：直接送 raw JSON，顶层及 nested task/settings 的重复 key（含转义后相同 key）均在 strict decode 阻断，native 调用数为 0；相同值的重复 key 也拒绝，不能先转 dict 或 canonicalize 再测。

```python
assert context.text.doc.dockey == unit_paper_id
assert context.text.source_locator == unit["source_locator"]
assert context.text.section == unit["section"]
assert result["evidence"][0]["source_text"] == context.text.text
assert bridge_aget_evidence_calls == 1
assert diagnostic["terminal_context_error_count"] == 1  # real terminal error case
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_paperqa2_corpus_bridge.py -q`。
- [ ] **Step 3: 实现原生适配与 offline native driver。** Settings(**frozen_settings)，每paper建Doc/Text，await docs.aadd_texts(texts,doc,settings)，最后 await docs.aget_evidence(task["question"],settings=settings)。使用 spec 三个 Text/source mapping，直接读 PQASession.contexts；不调用展示过滤、不反解析name、不增加 relevance阈值。Doc/Text数量、section、strictunicode、模型/实际模块路径/cleancheckout/tag/version验证，完全重复消除/冲突重复拒绝，按(paper_id,source_locator)排序。corpus不得调用旧 omit-surrogate helper，旧document regression保持。diagnostics覆盖ingestion/evidence全过程，识别 LogRecord.exc_info 的真实 LLMContextError；警告/stderr关键词不是terminal错误，任何terminal错误整次失败。finally capture failure 不伪报0。
- [ ] **Step 4: 运行 green与 pinned offline验收。** `& $rlrPython -m pytest tests/test_paperqa2_corpus_bridge.py tests/test_paperqa2_bridge_transport.py -q`。从获准测试项目既有 binding读出 $boundPqaPython、$testBindingPath：`& $boundPqaPython tests/paperqa2_corpus_acceptance.py --case native-identity --binding-file $testBindingPath`，再同命令 --case native-diagnostics。要求实际 pinned Doc/Text hash/set/session保留source字段；真实 map_fxn_summary处理可控model输出：正常score0合法空、不可重试/两次失败实际logger.exception被handler捕获、原生内部重试恢复无terminalcount。不能只mock COMPLETE、patch map_fxn_summary或伪造LogRecord作为nativegate。缺pinned能力BLOCKED，暂停依赖Task5；不自动安装。

## Task 5: 复用 ProcessRunner 的完整输出与 completion

**Files:**
- Modify: src/research_loop/l05_curie/paperqa2_runtime.py:149（现有 backend）。
- Create: tests/test_l05_curie_corpus_process.py。
- Reuse: src/research_loop/process_runner.py，不修改它。

**Interfaces:**
- 扩展 PaperQA2SubprocessBackend.execute_corpus(*, project_dir: str | Path, task: dict, settings: dict, worker_dir: str | Path, acquisition_run_id: str, attempt_index: int) -> dict；成功返回 {result,completion,result_ref,completion_ref}。已知失败持久化同 execution receipt，抛现有 PaperQA2ExecutionError/IntegrityError并附实际receipt；未知保留不确定状态，不推进controller。
- 私有 _CorpusOutputObserver 的 on_stdout(chunk: bytes) / on_stderr(chunk: bytes)，stream raw capture、flush/fsync/hash。
- validate_corpus_completion(completion: dict, *, task: dict, result: dict | None, process_logs: dict) -> dict，位于同 runtime owner；纯验证输入的实际已读取 log facts，manifest统一调用，不新增registry。

- [ ] **Step 1: 写失败测试。** test_stdout_over_256k_uses_full_spooled_json：受控真实子进程输出>256KiB JSON，memory stdout_truncated=True、完整file bytes/hash匹配，60长段可解析。test_observer_write_or_fsync_failure_blocks：partiallogs保留、PERSISTENCE_ERROR、不写成功pointer。test_exit0_terminal_diagnostic_blocks；test_timeout_nonzero_missing_wrong_duplicate_diagnostic_never_complete。test_raw_stdout_rejects_duplicate_json_keys：从真实子进程完整 stdout artifact strict decode，顶层及 nested evidence/runtime 重复 key（含相同值、转义后相同 key）拒绝，原始 bytes 保留、无成功 result/completion/pointer；不先转 dict，不把 canonical hash 一致当作原始输入无重复 key 的证明。路径测试包含relative逃逸、junction/symlink（平台可创建时）、dispatch前snapshot替换；不能靠ProcessResult mock覆盖实际process测试。

```python
assert process.stdout_truncated is True
assert stdout_path.read_bytes() == emitted_bytes
assert completion["stdout"]["byte_count"] == len(emitted_bytes)
assert completion["stdout"]["sha256"] == hashlib.sha256(emitted_bytes).hexdigest()
assert len(saved_result["evidence"]) == 60
```

completion 的 stdout/stderr execution 字段采用嵌套 object，各含 path、sha256、byte_count、truncated；process_terminal_state/returncode/terminal_context_error_count/process_tree_cleanup 等字段沿 spec，不把此测试结构变成第二通用 process schema。
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_process.py -q`。
- [ ] **Step 3: 在既有 backend 实现 corpus方法。** 相同boundinterpreter/bridge/repo/PQA_HOME/env、encoding UTF-8/errors strict、原timeout/treecleanup；dispatch前重读XML/hash/sourceunits和projectcontainment，核验Settings/runtime。Task4envelope送现有ProcessRunner observer；只从完整stdoutartifact strict decode，在形成 dict 前拒绝所有层级重复 key 和 NaN/Infinity，再交 Task1 纯 validator 与 canonical hash 核验；同一既有 RLR decoder 用于该契约 artifact 的读取/replay，不增加第二套 serializer。成功必须exited/exit0、有效Result、完整logs、diagnosticcount0；结果/completion复用现有immutable/atomicwriter。失败receipt同execution字段、typederror/result_sha256=null，无partial COMPLETE；原stdout仅诊断。completion精确按spec §9.2，memorytruncation不是完整artifact截断。不添加外层subprocessretry。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_process.py tests/test_l05_curie_paperqa2_runtime.py tests/test_runtime_plumbing.py tests/test_external_resilience.py -q`；预期 PASS，受控进程不运行模型。

## Task 6: 同一 checkpoint owner 的 worker/HTTP replay 事务

**Files:**
- Modify: src/research_loop/l05_curie/europepmc_runtime.py:89–260,820,2244,2575–2896。
- Create: tests/test_l05_curie_corpus_replay.py。
- Reuse: tests/test_l05_curie_europepmc_runtime.py 的 hostpause/freeze/onewriter cases。

**Interfaces:**
- continue_acquisition(project_dir: str | Path, cand_id: str, *, run_id: str | None = None) -> dict保持；explicitconfig进入同run_europepmc_acquisition controller，_host_context携带frozenbinding/worker边界，不建第二run_corpus_acquisition循环。
- _validate_focus_binding(project: Path, seed: dict, checkpoint: dict, *, attempt_index: int, evidence_focus: dict | None, freeze_context: dict) -> dict | None；shape调用Task1，核验真实request/assessment/receipthash/lineage/currentness；replay使用freeze_context。
- _worker_for_attempt(project: Path, checkpoint: dict, *, checkpoint_path: Path, task: dict, settings: dict, backend: PaperQA2SubprocessBackend, attempt_index: int) -> dict；PREPARED→durableIN_FLIGHT→Task5→validatedgroup→completionpointer。
- 现有replayable_http_get(url: str, timeout: int) -> bytes；v2entries区分SUCCESS/KNOWN_FAILURE/IN_FLIGHT；knownfailure重建原HTTPError/既有typedfailure，不增加通用errorclass。

- [ ] **Step 1: 写失败测试。** test_prepared_dispatch_once；参数化test_crash_windows：IN_FLIGHT只有stdout/result→BLOCKED不增call；完整group但无pointer→恢复无模型；knownfailure→重放原错误无重启；semantic/coveragepause同workerrefs。test_focus_replay_uses_freeze_time_binding：合法后来coverage不令旧task失效，不重新materialize；冻结时stale/cross-run/rawgap/missingreceipt/partialprojection拒绝且dispatchcount0。test_known_404_keeps_http_replay_slot：404→reserve→pause→replay同失败/顺序、networkcount不增；unknown不推进cursor。test_single_writer_and_frozen_settings：并发一次调用，修改projectconfig不能替换run配置。

```python
assert replayed_task_bytes == frozen_task_bytes
assert worker_call_count_after_resume == worker_call_count_before_resume
assert http_call_count_after_resume == http_call_count_before_resume
assert uncertain_outcome["kind"] == "blocked"
assert uncertain_outcome["reason"] == "uncertain_external_result"
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_replay.py -q`。
- [ ] **Step 3: 实现现有 owner 的 v2checkpoint。** 显式version分派，v1历史明确continuation不被_save盲目升级。freeze Settings/task/focus/origincontext为PREPARED；启动前IN_FLIGHT；完整validatedcompletion后才pointer/clearinflight。复用锁/writers/refvalidation，partialgroupBLOCKED。首轮null；后续默认完整合法gap投影，若采用null须冻结前明确记录，不因校验失败dropfocus。冻结semanticcontract/config，resume不重读项目config当新输入。HTTPknownfailure保留URL/status/classification/availablebytes/hash/物理retrylineage，失败占logicalcursor；沿用boundedretry/resourceclassifier，未知保持uncertain。no_new_sources只NOT_ATTEMPTED，不造空task/result/completion。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_replay.py tests/test_l05_curie_europepmc_runtime.py tests/test_host_handoff.py tests/test_http_resilience_wiring.py -q`；预期PASS。每crashcase assert HTTP/worker/hostcallcounts和真实diskhash，不能仅assert status。

## Task 7: 稳定 source extracts 与累计 semantic admission

**Files:**
- Modify: src/research_loop/l05_curie/europepmc_runtime.py:1115,1520,2748；Task2的typed mismatch。
- Create: tests/test_l05_curie_corpus_semantics.py。
- Reuse: SemanticEvidenceVerifier.verify、admit_reasoning_evidence、validate_evidence_extract、现有immutablecollision规则。

**Interfaces:**
- _verify_corpus_proposals(project: Path, *, task: dict, result: dict, cumulative_corpus: list[dict]) -> dict，返回 {located,rejected,proposal_refs}，稳定extract只有固定来源/parser/originalsnapshot，role=CONTEXT。
- _semantic_reuse_key(extract: dict, *, claim: str, contract_sha256: str, assessor_id: str) -> str，精确绑定四项，仍用既有semanticvalidator/ID/policy。
- 现有semanticcheckpoint/receipt表保存originattempt，currentattempt引用原verification/request/receipt；admittedset为稳定evidenceid并集。

- [ ] **Step 1: 写失败测试。** test_same_source_different_summary_score_same_extract_bytes：两attempt sameE_id/bytes/hash，proposalrefs不同、无falsecollision；sameIDdifferentbytesBLOCKED。test_semantic_replay_uses_base_claim_and_origin_receipt：focus改变claimhash不变，binding相同只一次host；extract/contract/assessor改变不可reuse。test_cumulative_preserves_unreturned_counterevidence：旧未再命中不删；CONTRADICTED+三个preservation为true准入，AMBIGUOUS/UNRELATED保留audit不准入。test_local_mismatch_vs_systemic_failure：单typedmismatch拒一条；全部定位失败/unknownpaper/profile/hash失败BLOCKED。

```python
assert extract1_bytes == extract2_bytes
assert proposal_ref1["task_id"] != proposal_ref2["task_id"]
assert semantic1["claim_sha256"] == semantic2["claim_sha256"]
assert semantic_host_call_count == 1
assert old_counterevidence_id in {e["evidence_id"] for e in cumulative_admitted}
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_semantics.py -q`。
- [ ] **Step 3: 同controller接source→semantic。** 用现有EuropePMC candidate UNVERIFIED形态，从taskunit恢复section；不使用带worker动态runtime的旧PaperQA2Candidate污染stableextract。独立SourceVerifier才LOCATED；retrieval固定engine/parser/sourcehash/snapshot，不带attempt/Settings/score/summary/result。proposal通过(evidence_id,task_id,task_sha256,result_sha256)关联；baseclaim精确Task1格式，现有五字段assessorpolicy不改。originreceipt重验、不伪造当前回答；累计获准并集不因本轮结果为空或低relevance清空。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_semantics.py tests/test_l05_curie_semantic_verifier.py tests/test_l05_curie_source_verifier.py tests/test_l05_curie_store.py -q`；预期PASS。summary/authority独特sentinel不进入extract/claim或取得LOCATED/verdict权限。

## Task 8: 当前 host 的科学 coverage 与 bounded routing

**Files:**
- Modify: src/research_loop/l05_curie/contracts.py:281；europepmc_runtime.py:2197,2431,2472,2575。
- Create: tests/test_l05_curie_scientific_coverage.py。
- Reuse: host_handoff.prepare_request/submit_response/load_response_receipt，不改通用schema/加registry。

**Interfaces:**
- judge_coverage(coverage: dict, *, round_index: int, max_rounds: int = MAX_ACQUISITION_ROUNDS, acquisition_state: dict | None = None) -> dict；五statefields/terminalreason枚举按spec §8.2，None保持legacy。coverage仍{covered,gaps}，由validatedassessment投影。
- _coverage_inputs(seed: dict, *, attempt_index: int, cumulative_corpus: list[dict], admitted_extracts: list[dict], semantic_refs: list[dict], previous_gaps: list[dict], acquisition_state: dict) -> dict，完整spec §8.1输入、不含unadmitted/summary。
- _coverage_scientific_input_sha256(inputs: dict) -> str，只绑定seed/baseclaim/corpussnapshotrefs/admittedextract+semantichashes/scope，排除budget/attempt。
- _coverage_for_attempt(project: Path, seed: dict, checkpoint: dict, *, checkpoint_path: Path, attempt_index: int, inputs: dict) -> dict，用stage coverage:<attempt_index>、同host，返回validatedassessment/originreceiptrefs给route/focus。

- [ ] **Step 1: 写失败测试。** test_results_section_not_scientific_coverage：有Results但范围不足gap/retry；test_counterevidence_can_be_sufficient：两维度可凭admitted反证PASS。test_invalid_coverage_rejected_before_immutable_receipt：漏/多维度、重复gap、false无gap、true无evidence、unadmittedref、错requesthash/authorityextra拒绝、无持久answerreceipt。test_budget_routes_without_pack_round_forgery：attempt3/corpus90无gapPASS、有gapSTOP、有余量RETRY，终止事实错配拒绝。test_no_new_sources_reuses_origin_assessment：currentbudget重算STOP、原request/answerhash不变；firstemptycorpus真实hostgap、workerNOT_ATTEMPTED。

```python
decision = judge_coverage({"covered": [], "gaps": [gap]}, round_index=1,
    acquisition_state={"attempt_index": 3, "max_attempts": 3,
        "corpus_count": 90, "corpus_limit": 90,
        "terminal_reason": "attempt_budget_exhausted"})
assert decision["verdict"] == "INSUFFICIENT_STOP"
assert decision["round_index"] == 1
assert not invalid_answer_receipt_path.exists()
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_scientific_coverage.py -q`。
- [ ] **Step 3: 实现host边界/route。** _host_request为coverage设完整科学tools_policy，不能复用semantic-onlypolicy。submit先Task1validator验request/refs/dimensions/membership，再通用hostsubmit持久化；replay同样验证。v2 checkpoint保存coverage requests/responses/assessments/pending；新mode停用结构性_coverage_for。terminalreason由已核验planner/discovery/budget事实，contracts唯一判verdict、caller不改写。scientificfingerprint相同才originassessmentreuse，变化则新的host请求，不改旧requesthash。validatedpersistedgaps才供planner/focus，不加focuscognitionstage/semanticcoveragecorrectiveloop。INSUFFICIENT_STOP保留feedback/manifest，不写PASSpack或改候选状态。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_scientific_coverage.py tests/test_l05_curie_contracts.py tests/test_host_handoff.py tests/test_l05_curie_gap_loop.py -q`；预期PASS。独特summary/unadmitted/toolssentinel验证input排除，各coveragebase问题完整一致。

## Task 9: v3 manifest、freeze recovery 与 L1消费闭合

**Files:**
- Modify: src/research_loop/l05_curie/europepmc_runtime.py:1227,1475,1490,1611；src/research_loop/l05_native_binding.py:277,329。
- Create: tests/test_l05_curie_corpus_integration.py。
- Modify tests: tests/test_l05_native_evidence_binding.py、tests/test_l05_native_l1_handoff.py、tests/native_curie_test_support.py。
- Reuse: store的build/preview/freeze/load frozenpack，不复制事务。

**Interfaces:**
- _validate_acquisition_manifest保持现有签名，显式v2/v3分派，v3强制完整provenance，委托各canonicalvalidators。
- validate_europepmc_acquisition_result(project_dir: str | Path, candidate_id: str, result: dict) -> dict保持；v3输出L05EuropePmcAcquisitionResult/v2，旧v2manifest仍resultv1，不全局改常量假升级。
- runtimeowner：validate_corpus_acquisition_for_pack(project_dir: str | Path, *, seed: dict, pack: dict) -> dict；用已有paths/firstowner/runbinding解析并调用同manifestvalidator，核对frozenpackhash/membership/version。nativebinding新mode消费时调用，不用项目当前config推断历史mode。

- [ ] **Step 1: 写失败测试。** test_three_attempts_freeze_one_v1_pack：workercorpora30/60/90、semantic/coveragepauses、最后packv1/decisionround1，HTTP旧refs为origin。test_manifest_tampering_blocks_l1参数化task/focus/completion/Settings/corpusorder/budget/semantic/coveragereceipt，每处篡改hash/ref均阻断。test_freeze_crash_windows_recover_without_external_calls：freeze_input→pack→manifest→binding之间重启、network/model/hostcount不增。test_committed_reentry_revalidates：不能直接回cachedresult。test_missing_new_provenance_never_legacy_fallback：删v3manifest/receipt/coverageorigin/newmode标记拒绝；真实旧frozen仍按原schema独立读验、不补新refs。

```python
assert worker_corpus_sizes == [30, 60, 90]
assert frozen_pack["version"] == 1
assert all(d["round_index"] == 1 for d in decisions)
assert committed_result["schema_version"] == "L05EuropePmcAcquisitionResult/v2"
assert external_call_counts_after_recovery == external_call_counts_before_recovery
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_integration.py tests/test_l05_native_evidence_binding.py tests/test_l05_native_l1_handoff.py -q`。
- [ ] **Step 3: 扩展manifest/freeze/native消费。** attempt source_snapshots仅Ni，cumulative引用Ci/origin；NOT_ATTEMPTED不造task/result。validator逐项验group、Settings/runtime、focus冻结时binding/question、corpus单调性、stableextract/semanticreuse/coveragefingerprint和最终route。COMMITTED也再验result，不信cache。PASS沿现有freeze_input→store→manifest→nativebinding，source_run_id/owner模式明确且新mode强制v3；缺新文件不能推断legacy。历史分派须有实际历史artifact/schema支持，不fabricatecorpusprovenance。nativeL1不能读proposal。既有pack/nativebindingwire约束保持；若需新必需bindingwire字段而原版本不允许，STOP提schema设计审核，不能caller bypass。
- [ ] **Step 4: 运行 green。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_integration.py tests/test_l05_native_evidence_binding.py tests/test_l05_native_l1_handoff.py tests/test_l05_curie_store.py tests/test_l05_curie_europepmc_runtime.py tests/test_l05_curie_provenance_hardening.py -q`；预期PASS。失败/insufficiency无L1ready，候选/frontmatter不变，核对diskbytes。

## Task 10: 唯一配置/公开协议接线与退役路径

**Files:**
- Modify: src/research_loop/deep_research.py:192、src/research_loop/commands/lifecycle.py:1154、src/research_loop/runtime_preflight.py:86、src/run_loop.py:2650,2751。
- Modify: docs/AGENT_NATIVE_RUN.md、docs/AGENT_CONTEXT.md、README.md、既有reuseaudit。
- Modify tests: tests/test_agent_native_cli_integration.py、tests/test_l05_curie_p1_wiring.py、tests/test_runtime_plumbing.py、tests/test_l4_paperqa2_document_runtime_v2.py。

**Interfaces:**
- 既有runtimeconfig paperqa2子对象的worker_mode/settings/acquisition_budget调用Task1validator，Task6freeze；不建配置文件。
- runtime_from_config(config: object) -> PaperQA2CurieRuntime与require_bound_paperqa2(spec)保持L4/document语义；同paperqa2_runtime新增corpus_backend_from_config(config: dict) -> PaperQA2SubprocessBackend供acquisitionowner，不全局替换L4requirement。
- src/run_loop.py::host_protocol_submit识别coverage:<attempt>，仍委托同submit/continue；host-next/host-submit公开参数/status/receipt保持。

- [ ] **Step 1: 写失败测试。** test_public_host_submit_routes_coverage_to_l05owner：真实CLIentry planner→worker→semantic→coverage→continuation，currentrequest/cursor/receipt/hash一致。test_corpus_required_capability_keeps_l4_optional_config：corpus缺配置failclosed，L4/旧document不因缺corpussettings失败。test_legacy_commands_cannot_take_corpus_owner_or_fallback：原PDFmap契约不变、新firstowner不被旧命令接管；retiredhelper都raises sentinel，新path仍正确，软件故障无fallback。

```python
assert submitted_stage == "coverage:1"
assert l05_submit_call_count == 1
assert response_receipt["request_sha256"] == pending_request["request_sha256"]
assert legacy_fallback_call_count == 0
assert candidate_bytes_after_stop == candidate_bytes_before_stop
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_agent_native_cli_integration.py tests/test_l05_curie_p1_wiring.py tests/test_runtime_plumbing.py tests/test_l4_paperqa2_document_runtime_v2.py -q`。
- [ ] **Step 3: 配置/公开协议接线并记录退出。** preflight保留已有binding/新settings，仅explicitcorpus验证requiredcapability；controller续用freeze。run_paperqa2_europepmc_acquisition不变第二authoritative循环。新path退出lexicalscore、perpaper320chars/32terms、sparsemanualretrieval/MMR、skip-summary、fuzzyalignment、R/D/Csieve、structuralcoverage、软件失败fallback。legacy/L4仍有caller的helper不删除，文档说明旧契约不具新readiness；旧公开命令不静默改参数。更新实际audit/操作文档，不改AGENTS，查全caller图、确认无第二owner/config/fallback。
- [ ] **Step 4: 运行 green与完整离线回归。** 同Step2四文件先PASS，再 `& $rlrPython -m pytest -q`、`git diff --check`、`& $rlrPython run_loop.py --help`、`& $rlrPython research_loop_v04.py --help`，要求PASS/exit0。baseline环境/fixture错误先分类，不弱化生产契约掩盖。实际完整change paths送 `tools/external_reuse_gate.py check --repo-root . --changed <路径清单> --diff-known true`，要求PASS/allowed_to_proceed=true；本计划轮docs-onlyNA不能代替实施gate。审核wholechange/contract/context/provider/CLI回执。

## Task 11: pinned-native / 真实 acceptance 与 readiness

**Files:**
- Modify: tests/paperqa2_corpus_acceptance.py（Task4driver，补live-corpus）。
- Modify tests: tests/test_l05_curie_corpus_integration.py。
- Produce: 获准一次性测试项目既有08_Audit/l05_acquisition artifacts、reports/<实际验收日期>-l05-paperqa2-cumulative-corpus-acceptance.md。
- 本 task 不自动修生产代码；首个真实错误先分类、停依赖执行，再决定owner修复是否仍在已授权范围。

**Interfaces:**
- driver仍读现有binding/ResearchSeed，通过既有host-next/host-submit/controller运行；current-host cognition 必须由当前 Codex session 完成，planner/semantic/coverage 回答按现有 request/tools_policy/validate→persist protocol 提交。driver 遇到 NEEDS_HOST 可暂停并交回现有 request/ref，当前 session 完成 host-submit 后通过同一 binding/controller 恢复；仅复用现有 checkpoint/request/receipt，不直接写state/pack、不自建discovery或hostcognition循环，也不得调用另一个模型、headless provider 或新 agent 模拟 host。PaperQA2 已绑定的 embedding/summary worker 调用边界保持。report从actualreceipts计算calls/语料证据数/hash/耗时/可得成本，不可得留UNKNOWN。
- live科学/网络/模型执行是独立阶段门，须用户授权project/input/binding和30/60/90资源预算；计划批准/离线green不自动授权科研运行。

- [ ] **Step 1: 写driver失败测试。** test_acceptance_driver_uses_public_protocol：只消费公开controller、不fabricatecheckpoint；test_needs_host_pauses_and_resumes_same_request：NEEDS_HOST 是正常协议暂停，交回 pending request/ref，driver 的 host model/provider 调用数为 0；经现有 host-submit 获得合法 receipt 后恢复同 run，不伪造 host 回答、不新建 cognition owner、不重复已完成 HTTP/worker 调用。test_first_blocker_marks_later_stages_not_attempted：原始错误保留，未达阶段NOT_ATTEMPTED，synthetic不称realacceptance。

```python
assert acceptance["worker"]["status"] == "BLOCKED"
assert acceptance["coverage"]["status"] == "NOT ATTEMPTED"
assert acceptance["l1"]["status"] == "NOT ATTEMPTED"
assert acceptance["worker"]["raw_error_path"] == original_error_path
```
- [ ] **Step 2: 运行 red。** `& $rlrPython -m pytest tests/test_l05_curie_corpus_integration.py -q`；新driver行为FAIL。
- [ ] **Step 3: 实现窄driver/report并离线green。** 复用Task4casehandler/strictfixtures，NEEDS_HOST 时暂停/返回现有 pending request/ref，不当作 blocker 或另开模型自动回答；沿既有 continuation 恢复，不新增 host 模型配置或 cognition loop。report引用rawpaths/hash、不含credentials；Step2预期PASS，再跑Task4两个pinned-nativecases，真实errorbranch和moduleidentity必须PASS，不预填live结果。
- [ ] **Step 4: 独立授权后跑真实case。** 用户指定$testBindingPath：`& $rlrPython tests/paperqa2_corpus_acceptance.py --case live-corpus --binding-file $testBindingPath`，driver在RLR环境调用公开controller，worker仍由项目binding的PaperQA2解释器执行；offline native cases只在PaperQA2环境加载原生包，不能跨环境import RLR。每次 NEEDS_HOST 暂停，由当前 Codex session 经既有 host-next 读取该 request、完成 planner/semantic/coverage cognition，并经 host-submit 提交；driver 随后沿同 run 恢复，不自行调用另一个模型模拟 host。真实EuropePMC XML、embedding/summary至少验证多篇/多轮/validatedfocus、pause/replay、反证/insufficiency。30/60/90性能须真实授权且发现足够来源，来源不足如实记录、不pagination/造replan/改coverage逼满。早期PASS后，资源检查须单独获准测试输入/run，不能改同runassessment。最长paragraph不截断，timeout/memoryfailure留BLOCKED；costunknown如实，首错停。
- [ ] **Step 5: 审核readinessreport。** 正常空与terminalerror有不同receipt；恢复无新模型调用；稳定claim/location/hash/corpus/pack可复核；未获准路径不能L1advance。只有相应离线suite/pinnedgate/获准realcase实际回执才可声明对应完成；live未授权/未达90则NOT_ATTEMPTED/未测，不称最大性能或scientificrecall通过。停止交付，无明确请求不commit/push/merge/deploy。

## Spec覆盖与self-review

| Spec章节 | 计划owner / 验证 |
| --- | --- |
| 1–3 目标/whole-system/唯一dataflow | Global约束与owner图；Task1audit、4nativeAPI、6controller、10retirement |
| 4 binding/Settings/预算 | Task1config/hash、3successfulsource预算、5timeout、6freeze、10capability、11实测 |
| 5 eligibility/cumulative/parser | Task2scope/location、3allocation/aliases、6HTTP、9monotonicvalidator |
| 6 Task/Result/focus/identity/capture | Task1shape/hash/question、4nativeidentity/diagnostics、5capture、6provenance/replay |
| 7 stableextract/admission/receipts | Task7及9消费验证，复用现有semanticpolicy/storewire |
| 8 hostcoverage/route/stop | Task1validator、8host/route/fingerprint、10publicsubmit |
| 9 versions/transaction/recovery | Task6worker/HTTP、9manifest/freeze/COMMITTED/native、10legacy |
| 10 failures/diagnostics | Task2typedmismatch、4真实nativebranch、5process/persistence、6uncertain、7systemfailure、8hostcontract |
| 11 reuse/retirement/compatibility | Task9历史与新provenance、10caller/CLI/L4/fallbacksentinels |
| 12 acceptance/未验证声明 | Task11实际回执，软件行为与科学recall严格区分 |

Self-review结论仅针对计划：全部12节已映射；Task1只验focusshape、Task6验冻结时provenance、Task8产生validatedpersisted来源、Task9按冻结时binding消费，未产生竞争claim/coverageowner。已核对接口名/参数/返回keys、TDDred/green与依赖顺序、五项ReviewFocus的test归属；Task4offline原生gate独立于Task5后续controller。新增生产函数留既有owner，不复刻成熟系统。性能/diagnostics/recall仍须实际验收，不标记已实现。

所有checkbox保持未完成；不从文档存在推断实施进度。选择子agent方式后才能按subagent-driven-development派生并明确文件ownership，本轮未派生；选择本会话方式则按executing-plans逐task推进、保留审核边界。

计划轮文档验证回执（2026-10-01）：strict UTF-8/no BOM、fence、连续11个task、45个未完成步骤、两条本地链接、无占位符/尾部空白检查PASS；11个Python断言示例仅通过AST语法检查，没有运行其中测试。既有reuse audit validate=true；仅本轮新增plan路径的完整changeset运行reuse gate，返回NOT_APPLICABLE、allowed_to_proceed=true，不代表原有dirty生产代码通过gate。git diff --check退出0。原spec、audit、AGENTS和三份既有dirty生产文件hash与本轮起点相同。本轮只新增本计划，没有pytest、科研检索、模型调用、安装、commit/push或worktree修改。

本轮三项最小修订 self-review（2026-10-01）：spec/plan 批准状态已登记，plan 绑定批准后的 spec SHA-256；dict 纯 validator 的重复 JSON key 检测承诺移至 Task4 raw stdin / Task5 raw stdout strict decoder 测试，canonical invariant 与既有 serializer 复用保持；Task11 live cognition 明确只由当前 Codex session 经现有 host-next/host-submit 完成，NEEDS_HOST 暂停/恢复不引入另一个模型或 cognition owner。其余任务、预算、wire 和 authority 保持；所有 checkbox 仍未完成，没有执行 Task1、pytest 或 live acceptance。

**停止条件：本轮最小修订、self-review 和文档验证完成后停止；不开始 Task 1。spec 与 plan 的 APPROVED 状态不自动授权实施或 live acceptance。**
