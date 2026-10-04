# PaperQA2 cumulative corpus：Task 1–10 实施报告

报告日期：2026-10-02（用户时区 Asia/Shanghai）；文件名沿用获批计划标识日期2026-10-01。

范围：已批准 architecture spec 和 implementation plan 的 Task 1–10。本报告仅汇总本轮软件实施及离线验证。Task 11 = **NOT AUTHORIZED / NOT ATTEMPTED**。真实 Europe PMC、真实 embedding/summary、current-host scientific cognition 和真实30/60/90 acceptance 未执行；pytest green 不代表真实科研 E2E。

## 基线和授权

- 仓库：`D:/research_loop/main`；branch `review/l05-p1-final-diff`；HEAD `c60632afdb3aabd6e7c55ffea8dd6a43c50c7982`。没有 commit、push、merge 或重置。
- Spec approved v1.1，SHA-256 `86670dd9c8f83968abe9ce07f9af367fff3117026037ca4c0a1a93c92e9e6b7c`。
- Plan approved v1.0，SHA-256 `d94170fd5a3d0a8b63dc97e0ae194d16252f06c272760cecbf6313f9a0519fc0`。
- Python：`C:/Users/hk200/miniforge3/envs/rlr/python.exe`；PaperQA2 repo `D:/research_loop/paper-qa`，clean HEAD `57e89f7223b0960d5ee5ea048c69e3c47e088572`、tag `v2026.08.12`。
- 起始 dirty：AGENTS、europepmc_runtime、selector、l05_curie_cli，以及已存在的 spec/plan/reuse audit。AGENTS、CLI、approved spec/plan 的原始哈希保持；runtime/selector 原先 max_papers=30 修改保留。
- 用户 reset 后核对 HEAD 和实际文件，延续 ledger，没有重新执行已完成 Task。
- 证据目录：[执行 ledger / 日志 / 原始 baseline 目录](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus>)；[受保护文件哈希核对](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/protected-file-check.json>)。

## 逐 Task 结果

计数为该 Task 的实际 task-done 最终 targeted run；文件集有重叠，不能相加当成唯一测试数。

| Task | 状态 | collected | passed | failed | skipped | 最终 targeted 回执 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| TASK_1 | PASS | 109 | 109 | 0 | 0 | [task-1-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-1-tests.log>) |
| TASK_2 | PASS | 70 | 70 | 0 | 0 | [task-2-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-2-tests.log>) |
| TASK_3 | PASS | 23 | 23 | 0 | 0 | [task-3-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-3-tests.log>) |
| TASK_4 | PASS | 15 | 15 | 0 | 0 | [task-4-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-4-tests.log>) |
| TASK_5 | PASS | 57 | 56 | 0 | 1 | [task-5-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-5-tests.log>) |
| TASK_6 | PASS | 119 | 119 | 0 | 0 | [task-6-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-6-tests.log>) |
| TASK_7 | PASS | 66 | 66 | 0 | 0 | [task-7-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-7-tests.log>) |
| TASK_8 | PASS | 55 | 55 | 0 | 0 | [task-8-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-8-tests.log>) |
| TASK_9 | PASS | 150 | 150 | 0 | 0 | [task-9-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-9-tests.log>) |
| TASK_10 | PASS | 32 | 32 | 0 | 0 | [task-10-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task-10-tests.log>) |

Task 5 的1项 skipped：Windows 无创建 symlink 权限，该案例未验证；正常路径、逃逸和其他路径检查有独立通过案例。

1. 在现有 contracts / paperqa2 / runtime owners 定义严格 Task、Result、config、scientific coverage 和 canonical hash；duplicate key 由 raw decoder 检测。
2. 扩展同一个 JATS parser / SourceVerifier 为显式 v2，全正文、caption、原始合法编码和 canonical locator；legacy/L4 默认 v1。
3. 复用 canonical alias 冲突规则；机械 query/provider allocation，每轮最多新增30、累计90；原始 provenance append-only。
4. 同 bridge 的显式 corpus mode，调用实际 pinned Docs.aadd_texts/aget_evidence；Doc.dockey=paper_id，Text.source_locator/section；terminal diagnostics fail closed。
5. 复用 ProcessRunner 和 immutable writer，保留完整原始 stdout/stderr、completion、hash；严格 JSON/UTF-8；timeout 清理进程树。
6. 同 checkpoint/controller 冻结配置、Task、focus；PREPARED/IN_FLIGHT/complete group replay；不确定结果不能重跑冒充成功；保留实际 HTTP 失败证据。
7. 独立重读全部 source XML，稳定 extract；四项绑定复用原始 SemanticVerifier receipt；worker score/summary 不取得科学 authority。
8. 同 current-host handoff 的全问题 scientific coverage；同 judge_coverage 路由；validated persisted gap 才能成为后续 focus，semantic claim 永久冻结。
9. 同 manifest/store/native-binding 完整 provenance 闭合，30/60/90 受控离线 controller 测试；COMMITTED 重新验证、crash recovery、篡改和缺失 provenance fail closed。
10. 唯一 runtime config 保留 settings；单独 corpus capability；公开 host-submit 接 coverage；legacy first-owner 隔离，retired helper sentinel；L4 document factory 保留。

## 实际验证命令与完整回归

统一 targeted 环境：`PYTHONPATH=src`、`PYTHONNOUSERSITE=1`、`PYTHONUTF8=1`；完整回归另外设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`。

| Task | 实际最终命令（Python路径同上） |
| --- | --- |
| 1 | `python -m pytest tests/test_l05_curie_corpus_contracts.py tests/test_l05_curie_contracts.py tests/test_l05_curie_paperqa2.py tests/test_l05_curie_paperqa2_runtime.py -q` |
| 2 | `python -m pytest tests/test_l05_curie_europepmc_evidence.py tests/test_l05_curie_source_verifier.py tests/test_l4b_closed_corpus_fulltext.py tests/test_l4b_paperqa2_evidence_wiring.py tests/test_l05_curie_paperqa2_runtime.py -q` |
| 3 | `python -m pytest tests/test_l05_curie_corpus_allocation.py tests/test_l05_curie_provider_alias_identity.py tests/test_l05_curie_canonical_identity_integration.py tests/test_l05_curie_selector.py -q` |
| 4 | `python -m pytest tests/test_paperqa2_corpus_bridge.py tests/test_paperqa2_bridge_transport.py -q` |
| 5 | `python -m pytest tests/test_l05_curie_corpus_process.py tests/test_l05_curie_paperqa2_runtime.py tests/test_runtime_plumbing.py tests/test_external_resilience.py -q` |
| 6 | `python -m pytest tests/test_l05_curie_corpus_replay.py tests/test_l05_curie_europepmc_runtime.py tests/test_host_handoff.py tests/test_http_resilience_wiring.py -q` |
| 7 | `python -m pytest tests/test_l05_curie_corpus_semantics.py tests/test_l05_curie_semantic_verifier.py tests/test_l05_curie_source_verifier.py tests/test_l05_curie_store.py -q` |
| 8 | `python -m pytest tests/test_l05_curie_scientific_coverage.py tests/test_l05_curie_contracts.py tests/test_host_handoff.py tests/test_l05_curie_gap_loop.py -q` |
| 9 | `python -m pytest tests/test_l05_curie_corpus_integration.py tests/test_l05_native_evidence_binding.py tests/test_l05_native_l1_handoff.py tests/test_l05_curie_store.py tests/test_l05_curie_europepmc_runtime.py tests/test_l05_curie_provenance_hardening.py tests/test_l05_curie_corpus_allocation.py -q` |
| 10 | `python -m pytest tests/test_agent_native_cli_integration.py tests/test_l05_curie_p1_wiring.py tests/test_runtime_plumbing.py tests/test_l4_paperqa2_document_runtime_v2.py -q` |

- 完整离线回归：`python -m pytest -q` → **2088 passed, 1 skipped, 2 warnings in 1715.85s (0:28:35)**；[full-offline-tests.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/full-offline-tests.log>)。
- Final fix targeted：61 passed in 181.43s (0:03:01)；[final-fix-green.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/final-fix-green.log>)。Driver修正：41 passed, 1 skipped in 13.38s；[final-process-driver-green.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/final-process-driver-green.log>)。
- 首次完整回归因 reset/usage limit 中断，无终止汇总，未计为通过；保留[full-offline-interrupted.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/full-offline-interrupted.log>)。
- CLI：`python run_loop.py --help` 和 `python research_loop_v04.py --help` 均 exit 0；[run-loop-help.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/run-loop-help.log>)、[research-loop-help.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/research-loop-help.log>)。
- `git diff --check` exit 0；[diff-check.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/diff-check.log>)。
- 完整实施路径的 architecture/reuse gate：[task10-reuse-gate.json](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task10-reuse-gate.json>)；实际状态须见最终 ledger。

## 原生 PaperQA2 的离线证据

Task 4 用 actual pinned native API 和受控 provider adapter：identity 验证 Doc/Text/Context、hash/set/deepcopy 后 source identity；diagnostics 验证真实 native summary map 的 score0、两次解析失败、可恢复 retry、不可恢复 timeout。没有调用真实 embedding/summary model。

- `python tests/paperqa2_corpus_acceptance.py --case native-identity --binding-file D:/research_loop/_runtime/agent-native-live-acceptance-20260930T041910Z/project/00_Preflight/deep_research_runtime.json` → PASS。
- 同命令 `--case native-diagnostics` → PASS。绑定文件仅只读定位 installed runtime；该历史项目未运行或修改。
- [task4-native-identity.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task4-native-identity.log>)；[task4-native-diagnostics.log](<D:/research_loop/main/.superpowers/sdd/2026-10-01-l05-paperqa2-cumulative-corpus/task4-native-diagnostics.log>)。

## Red、失败分类和修复

每个 Task 先观察 targeted red，确认缺少计划行为，再最小修改相应 owner。下面保留唯一的分类摘要；完整首次失败在证据目录。

- - 3 -> 6/9: ordered cumulative corpus, origin snapshots and alias ownership; append-only and successful-new budget coherent.
- Task 1: red 78 collected / 78 failed, all missing planned interfaces; baseline 29 passed. Review identified PRODUCTION BUG: Unicode error and incomplete/unpinned expected runtime were not domain-validated; two additional tests red, fixed in existing owners.
- Task 2 red: 20 collected, 9 failed / 11 passed; new parser_profile and typed mismatch missing. Green: 70 collected / 70 passed. Diff/caller review: default v1 retained; existing L4 parser and verifier callers remain compatible; v2 same node/locator map, no text dedupe/truncation. Unsectioned source section labels are Abstract/Body; source text and canonical locator are authoritative.
- Task 3: initial red 8/8 missing APIs; boundary red 3 failed (duplicate frozen alias, preparation still calling scorer, 70+30 budget overrun). Driver review corrected synthetic source IDs to be unique. Pure matching/allocation and the same preparation/execution owner now extended. Expanded regression 101 collected / 101 passed in 51.96s including existing acquisition runtime.
- Task 4 red: 14 collected / 14 failed, missing corpus bridge. Green boundary: 15 collected / 15 passed. Pinned offline native-identity PASS (actual Doc/Text/Context set/hash and original source identity), native-diagnostics PASS (score 0, real twice-failed summary parse, real recoverable retry, real non-retryable timeout branches). Controlled provider adapter only; no actual model/HTTP calls. Existing binding read-only: D:/research_loop/_runtime/agent-native-live-acceptance-20260930T041910Z/project/00_Preflight/deep_research_runtime.json, bound interpreter RLR Python; project not executed or modified. Logs task4-native-*.log.
- Task 5 DRIVER: controlled child stdin used Windows default encoding; corrected driver to read strict UTF-8 bytes. Import/timeout invocation errors in new owner test corrected before valid red; neither counted as behavior red.
- Task 5: Ruling: extend existing ProcessRunner bounded UTF-8 diagnostic decoding — legal full output fails at byte-cut head/tail, proven by 2 corpus cases and 3 real process owner tests; plan owner-map explicitly permits demonstrated owner changes — no alternate runner or caller bypass. Complete artifacts remain strict-decoded; malformed captured bytes and invalid real EOF still fail. Cost if wrong: diagnostic text behavior for truncated UTF-8 callers; covered by targeted owner tests and existing resilience regression.
- Task 5 review: malformed diagnostic previously escaped receipt creation; new actual child case RED, handled in same completion/log-facts owner. Partial raw logs retained, no result on failure.
- Task 6 red: 15 missing worker/focus/version cases; controller red 2 missing config freeze / known failure replay cases. Review RED actual absent durable receipt, checkpoint path escape, and 4 missing v2 binding fields; fixed at same owners. Initial coverage fixture accidentally used a different shape, corrected to actual Task 1 contract before evaluating it.
- Task 7 initial red 14/14 missing source/reuse interfaces. Review 2 RED: empty contexts hid damaged snapshot; raw duplicate semantic field was persisted after dict decoding. Fixed by independently rereading all task sources and reusing strict raw decoder before new-mode host submission.
- Task 8 red 28 cases missing acquisition-state routing/scientific request owner, plus 2 public-controller cases invoking retired structural coverage. Empty discovery test helper incorrectly defaulted [] to a paper; corrected test driver to explicit zero-hit bytes, no production compensation.
- Task 8 diff review: same host handoff and Task 1 validator validate before persistence; one shared origin coverage proof helper serves focus and assessment replay. Scientific fingerprint excludes attempt/budget/previous gaps only; source/seed/claim/admitted semantics/scope remain bound. Existing contracts owner alone computes verdict; all pack round_index values remain 1.
- Task 9 red: 32 collected, 17 failed, 15 passed; production gap at existing store selection field. Expanded recovery proves missing pre-pack recovery, COMMITTED prepare revalidation, and shallow alias provenance mutation; each classified PRODUCTION BUG, no architecture gap. Driver fixes: restore worker counter wrapper on replay; all six discovery batches have 15 records within page_size=25.
- Task 9 reuse review: native binding delegates existing acquisition validator; worker completion read-only helper shared with replay; source verifier has explicit persist=False consumer mode; same source locators, store, first-owner, host receipt, semantic and coverage validators. No second worker/corpus registry.
- Task 10 red: 32 collected / 7 failed / 25 passed, missing public coverage dispatch, explicit corpus capability/config validation and preflight settings preservation. First green: 32 collected / 31 passed / 1 failed; DRIVER: reused project had consumed PROJECT_READY, so invalid-config fixture correctly stopped at readiness guard (code 3). Invalid binding now tested in a separate fresh project; production guard unchanged.
- Final review red: actual bridge-main subprocess strict UTF-8 cases 3 collected / 2 failed / 1 passed; invalid GBK-but-not-UTF8 bytes accepted and valid non-ASCII corrupted. Retry/coexistence first repro had DRIVER incorrect retained query/coverage round_index; corrected fixture to canonical v2 pack. Valid repro: 3 collected / 3 failed, missing first manifest for authorized retry or unrelated owner; production unchanged at red.
- Final DRIVER: independent process/replay check 42 collected / 15 failed / 26 passed / 1 skipped. Actual child stderr proves KeyError evidence_k: Task 9 controlled one-context extension placed normal-mode k at task top rather than task.budget. Correct driver to approved Task contract only; no production compensation.
- Final fix pass: re-grade both confirmed findings Important / PRODUCTION BUG. Bridge main now strict-decodes raw stdin UTF-8 before the same JSON decoder hooks, with no alternate serializer; in-process stdin fixture now supplies a real byte stream. Native binding validates first-acquisition provenance for canonical v1 only; existing retry authorization recursively loads/validates its actual parent, preserving initial corpus proof. Historical v1 pack is not owned by a different active first-owner run. No new owner, lifecycle or wire. Driver correction green: 42 collected / 41 passed / 0 failed / 1 skipped.
- Final: Ruling: reviewer set aside legacy/PDF redesign and unchanged semantic submission — retain existing contracts and run regression, do not expand implementation scope — cost if wrong: pre-existing bugs in those unchanged paths are not repaired here.
- Final deferred minors: none.
- Final targeted fix verification: 61 collected / 61 passed / 0 failed / 0 skipped in 181.43s, final-fix-green.log. Both Important findings have valid RED→GREEN evidence; full post-fix suite pending. No deferred minors.
- Final: fixed Important 1 strict stdin UTF-8 — test_actual_bridge_main_uses_strict_utf8_stdin valid/invalid byte cases RED→GREEN; existing duplicate/nonfinite boundary tests remain green; full suite 2088 passed / 1 skipped / 0 failed.
- Final: fixed Important 2 acquisition/authorized-retry version and owner dispatch — test_frozen_corpus_initial_pack_supports_existing_authorized_retry False/True plus test_historical_frozen_pack_coexists_with_different_active_first_owner RED→GREEN; deleting actual parent corpus proof still rejects retry binding; full suite 2088 passed / 1 skipped / 0 failed.

## 实际修改文件

以下为本轮可归属的实现路径，排除了未改的 AGENTS/CLI/spec/plan。新测试文件和新增离线 driver 包含在内；reuse audit 是原有文件的扩展。

| 文件 | SHA-256（最终实际 bytes） |
| --- | --- |
| [docs/AGENT_CONTEXT.md](<D:/research_loop/main/docs/AGENT_CONTEXT.md>) | `3b531c86517e6bd45cce7f2106171211072faa7779dc7f8ffa4c8543267d5423` |
| [docs/AGENT_NATIVE_RUN.md](<D:/research_loop/main/docs/AGENT_NATIVE_RUN.md>) | `25846f05c7408f5676b33d24a502e04d99f84bc082e1686c902ca82444522de5` |
| [docs/architecture/external-reuse/2026-10-01-l05-paperqa2-cumulative-corpus-design.json](<D:/research_loop/main/docs/architecture/external-reuse/2026-10-01-l05-paperqa2-cumulative-corpus-design.json>) | `ff847a09c8b1410d05dd9c5805156a955a71079f6d6c9294f79924f46281ec07` |
| [README.md](<D:/research_loop/main/README.md>) | `65918de8c83eb8922caae49072ce8c71eaad7e717bcf56d460dc3b54bfe22f8d` |
| [scripts/paperqa2_rlr_bridge.py](<D:/research_loop/main/scripts/paperqa2_rlr_bridge.py>) | `fb1aa4f62b004e1de2fcc5127f278959986ad80e79faf358a6e7820740387675` |
| [src/research_loop/commands/lifecycle.py](<D:/research_loop/main/src/research_loop/commands/lifecycle.py>) | `035c68044fffbf8484546a7f6f9e47aa437ba5f7993c4a1a7bcea31bbcc9139d` |
| [src/research_loop/deep_research.py](<D:/research_loop/main/src/research_loop/deep_research.py>) | `966a2e19dafa590b7d5d8d579c609c501d392209100805a98c8bbc79f66b4559` |
| [src/research_loop/l05_curie/contracts.py](<D:/research_loop/main/src/research_loop/l05_curie/contracts.py>) | `da43d290389d19f7a253fa72469f121e5f3099f2821db21be36efd602888c785` |
| [src/research_loop/l05_curie/europepmc_runtime.py](<D:/research_loop/main/src/research_loop/l05_curie/europepmc_runtime.py>) | `9c81ee7eec11a7ca4429227d5f202c4a217d66b5b7aaf8f658aea77591ed4620` |
| [src/research_loop/l05_curie/europepmc.py](<D:/research_loop/main/src/research_loop/l05_curie/europepmc.py>) | `753196930a4e14cf4aa9176f4bb6c934697e6bb34c4ce1a1fea745d8849a81f4` |
| [src/research_loop/l05_curie/multisource.py](<D:/research_loop/main/src/research_loop/l05_curie/multisource.py>) | `20d70cc88005c6bc0364949f9dd739dc2b250db4063a44409818d58c09241b44` |
| [src/research_loop/l05_curie/paperqa2_runtime.py](<D:/research_loop/main/src/research_loop/l05_curie/paperqa2_runtime.py>) | `2bfe3c79ab90adbc3e5467aa88169fbf5acb4694be0d2c11390f7f21d633a69e` |
| [src/research_loop/l05_curie/paperqa2.py](<D:/research_loop/main/src/research_loop/l05_curie/paperqa2.py>) | `017dba25892f750ad99138ed67281160e2a20b1bbfe6d5ee222019bf58282edd` |
| [src/research_loop/l05_curie/selector.py](<D:/research_loop/main/src/research_loop/l05_curie/selector.py>) | `e77895b1038e29cd835f4e644eb15e72f7b014755dbfd1deda4c5eda7a851000` |
| [src/research_loop/l05_native_binding.py](<D:/research_loop/main/src/research_loop/l05_native_binding.py>) | `411bbcb92f9f8e96d4e05054043a9403d220af5db95be222dbfdd31271660022` |
| [src/research_loop/process_runner.py](<D:/research_loop/main/src/research_loop/process_runner.py>) | `dafe525545af89d5034936ee20bf23c388881c364d78ee6e80e068eaaa1fb042` |
| [src/research_loop/runtime_preflight.py](<D:/research_loop/main/src/research_loop/runtime_preflight.py>) | `a3d46c68538a425ab0165f31d3d1b78bab6d7f243a62ed3955603449369fb84f` |
| [src/run_loop.py](<D:/research_loop/main/src/run_loop.py>) | `50b50edf48d839e3dc0ec761b0ba9b7defd9f79ab6761b9c208aec026b0b2442` |
| [tests/paperqa2_corpus_acceptance.py](<D:/research_loop/main/tests/paperqa2_corpus_acceptance.py>) | `a0eff8bcef95254d46f11a1adbd083458ddd59907da011028ad034b31c5e57f6` |
| [tests/test_agent_native_cli_integration.py](<D:/research_loop/main/tests/test_agent_native_cli_integration.py>) | `332a3dc47aae874aa281554fa4008968f271d6dc441450cd6da4b79b32ff636e` |
| [tests/test_l05_curie_corpus_allocation.py](<D:/research_loop/main/tests/test_l05_curie_corpus_allocation.py>) | `59409ea9b1cd3e5b391e47242cf6bce103d6ce381ca155b0de499d27ae164bf4` |
| [tests/test_l05_curie_corpus_contracts.py](<D:/research_loop/main/tests/test_l05_curie_corpus_contracts.py>) | `adff08ee8c5433bd1317f64fb7352efbd5bdbce888416ed0535047740e825a57` |
| [tests/test_l05_curie_corpus_integration.py](<D:/research_loop/main/tests/test_l05_curie_corpus_integration.py>) | `41f186abdef288208cfd00a1ef11d3100a8195ff4b8c0c3db4774451680dfd8d` |
| [tests/test_l05_curie_corpus_process.py](<D:/research_loop/main/tests/test_l05_curie_corpus_process.py>) | `b3218afe01f1c0915238da8bd5db77e07b98dfde234e9d0d26c30affacee13d2` |
| [tests/test_l05_curie_corpus_replay.py](<D:/research_loop/main/tests/test_l05_curie_corpus_replay.py>) | `9706c029d047fcc864bbbdeaab8a42bc273df24c6848ed91c0b5d187268800d5` |
| [tests/test_l05_curie_corpus_semantics.py](<D:/research_loop/main/tests/test_l05_curie_corpus_semantics.py>) | `798ba6d1298d2ddeb5aa7fa010900bd502cc36d53088bbe2416ab805ef9ae69c` |
| [tests/test_l05_curie_europepmc_evidence.py](<D:/research_loop/main/tests/test_l05_curie_europepmc_evidence.py>) | `fc64a29c5a16e42516d2524f5f47d44a4d749f5850c6001ce71ba792ffa9d28c` |
| [tests/test_l05_curie_p1_wiring.py](<D:/research_loop/main/tests/test_l05_curie_p1_wiring.py>) | `036d5d5d4f0612a3c4916a879bc9b472ecab567a1e75230b3a709089984c5247` |
| [tests/test_l05_curie_scientific_coverage.py](<D:/research_loop/main/tests/test_l05_curie_scientific_coverage.py>) | `4d2767887f19e50d9fbbcc5e2f4cc9daaa11efbf3be19c4b76f3849bd646bc5e` |
| [tests/test_l05_curie_source_verifier.py](<D:/research_loop/main/tests/test_l05_curie_source_verifier.py>) | `cea21714a6a829943db4892b65472f145b82a3babefcf0ba7b22db2b45a3d4db` |
| [tests/test_paperqa2_bridge_transport.py](<D:/research_loop/main/tests/test_paperqa2_bridge_transport.py>) | `a5f3a1032ed3a2791f05a0079886303dcfee5b48171a84c129021381719077b2` |
| [tests/test_paperqa2_corpus_bridge.py](<D:/research_loop/main/tests/test_paperqa2_corpus_bridge.py>) | `369667a0df484e693e9558d8c955c389feab34842cb42e673723ce3e5726ff9a` |
| [tests/test_runtime_plumbing.py](<D:/research_loop/main/tests/test_runtime_plumbing.py>) | `0ae7d5c7259a5697aa7baf61c4dc7e86ad57ef682a54ac177f2cd86e737379e7` |

本报告自身是另一个文档产物；执行工具、baseline 和完整日志保留在该计划的 ignored evidence workspace。

## Architecture / reuse gate

Native PaperQA2 拥有 retrieval / reranking / summary / relevance；RLR 保留 seed、source、semantic、coverage、persist/replay 和 state-transition authority。复用一个 canonical serializer、runtime config、first owner、checkpoint、acquisition controller、store、host handoff；没有新增 corpus registry、locator 系统或算法旁路。

Raw decoder 检测 duplicate JSON key；Doc.dockey 为 canonical paper_id；Text.source_locator/section 保存原 RLR JATS location。第一轮 focus=null；后续 focus 只来自绑定当前 coverage request 的 validated/persisted gap，写入 Task/hash/replay，仅改变 worker retrieval question。

## 最终独立审查

# 单次独立最终审查（修复前审查结论）

Reviewer：同一个 fresh-context code-reviewer，gpt-6-astra / max。第一次 turn 因账号 usage limit 中断；同一 reviewer 继续原审查并完成，没有新增 review seat、没有 re-review。只读检查 Tasks 1–10 的可归属工作树改动和实际调用链。

## Strengths

- 新 corpus 路径直接使用原生 Docs.aadd_texts/aget_evidence，没有重建检索、摘要或相关性算法。
- 原始 question/hypothesis、可选 focus、canonical paper ID 和 JATS locator 的职责清楚；summary/score 没有取得科学证据或 coverage 决策权。
- 完整 stdout 落盘、worker completion 恢复、原始 semantic/coverage receipt 重验均复用现有 owner；partial result 不被当作完成。

## Findings

Critical：0。Important/HIGH：2。Minor：0。

### 1. 实际 stdin 入口仍依赖 Windows 默认编码

修复前位置：scripts/paperqa2_rlr_bridge.py:319，调用方 paperqa2_runtime.py:416。

json.load(sys.stdin) 只将 stdout 配置为 UTF-8。调用方发送严格 UTF-8 bytes，却没有保证子进程 stdin 使用相同编码。在 GBK 管道环境下，合法非 ASCII question/path 会损坏或解码失败；非法 UTF-8 D6 D0 却被接受为“中”。后续 hash 检查无法恢复原始内容，不能保证在原生 worker 调用前拒绝。新 corpus 协议明确要求严格 UTF-8，旧入口不满足这个契约。

真实 main 入口回归测试仅用 echo 替换模型执行，final-stdin-red.log 记录2 failed / 1 passed。最小修复是在 bridge 入口显式严格解码 stdin UTF-8，保留 duplicate-key/nonfinite 检查；不能依赖终端预设环境变量。

### 2. 合法 L1 retry 和无关历史 pack 被误当成缺失首轮 provenance

修复前位置：l05_native_binding.py:95、europepmc_runtime.py:2025。

_load_pack 无条件进入 acquisition 验证。合法 retry 有自己的 source_run_id，不是首次 acquisition；继承 v2 source 时按 retry run 寻找首轮 manifest/checkpoint，被判缺少 mandatory provenance。无 manifest 时仅凭候选/round 共用 first-owner 文件存在就拒绝，没有核实 owner 属于当前 pack。全旧 profile 的合法 retry，以及与另一 unfinished run 共存的历史 frozen pack，也被拒绝。

现有 retry authorization、parent hash、gap lineage、store 检查已通过，新增分派错误导致失败。新增授权 retry 两种变体与历史 coexistence 测试；修正 fixture canonical round_index 后 final-retry-valid-red.log 仍记录3 failed。

最小修复：在既有 acquisition/native-binding owner 内按实际 pack version、首轮 owner、retry lineage 分派；retry 重验真正的 corpus parent provenance。保留现有 authorization，不伪造 retry 首轮 manifest、不放宽新 corpus 缺失证明的拒绝规则。

DRIVER：受控 process CHILD 的 evidence_k 层级错误已修正，41 passed / 1 skipped，不列为未解决生产 finding。

## 五项 Review Focus

1. Windows 路径别名、junction/symlink、TOCTOU：已检查 lexical path、resolved containment、dispatch 前独立 XML/hash/source_units 重验及 bridge 再验。提前替换有测试；Windows symlink 测试因权限跳过，真实 junction 并发替换未实测，不能声明无竞态。
2. 超长段落、同文不同节点、非法编码：v2 parser 保留完整段落和节点身份，corpus 分支拒绝 surrogate；实际 stdin 编码边界存在 Important 1。
3. 精确预算与 bool 冒充 int：严格整数、累计预算、有限 reserve promotion、独立 coverage 路由符合要求；预算耗尽不会覆盖合法 PASS。没有新增问题。
4. 落盘与 pointer 之间重启：完整 durable group 可恢复，partial group 阻断；冻结 task/settings/focus 与原始 receipt 重验保留。没有新增问题。
5. 历史 frozen 与新未完成 run 共存：缺新 provenance 的拒绝方向正确，owner/version 分派存在 Important 2。L4/document 分支与旧公开命令的独立入口已检查。

## Declined to judge（完整清单）

- 真实 Europe PMC、embedding/summary 服务兼容性、科学召回、真实30/60/90性能：Task 11 未授权、未执行。
- 整个上游 PaperQA2 或依赖生态的安全审计：仅核查固定版本相关 API、身份和诊断调用链。
- 重构既有 legacy/PDF 算法、未改动的非 corpus semantic 提交流程：不属于本次范围。
- 初始 dirty baseline、AGENTS、approved spec/plan 的既有内容：保留基线，不归属本次实现。
- 完整离线回归通过结论：审查时原运行没有终止汇总，不能从进度推定通过。

## 原始 Verdict

WARNING / Ready to merge: With fixes。两项均为已批准 owner 内的 PRODUCTION BUG，没有确认需要新增 owner、binding wire 或扩展阶段的 ARCHITECTURE GAP。修复后需要 targeted GREEN 和完整离线回归终止汇总。此次审查不构成 Task 11 readiness。

后续修复和验证以 progress.md 的 Final fixed / Final verification 回执为准；本文件保留修复前审查结论，没有声称审查者对修复重新审核。


## 全部 Rulings 与 deferred minors

使用 executing-plans 的一次 fresh-context reviewer。用户禁止提交，review-package 脚本因 empty commit range 返回3，按已记录裁决使用精确 baseline 对 working tree 的完整 attributable diff，包含 untracked 测试。

- Ruling: execute in current checkout — explicit current HEAD/dirty-preserving implementation request takes precedence over worktree creation guidance — existing work must be preserved; recorded baseline enables attributable diff.
- Ruling: preserve ledger/logs and use working-tree diff without commits — user prohibits automatic commit — receipts, not commit ranges, prove execution.
- Task 3 Ruling: preserve existing HTTP classifier but restrict corpus reserve promotion to its 404/410 results — spec 5.2/10.2 explicitly admits these known resource failures only; legacy healthy-control 500 logic unchanged — corpus 500 blocks even if legacy could promote.
- Task 5: Ruling: extend existing ProcessRunner bounded UTF-8 diagnostic decoding — legal full output fails at byte-cut head/tail, proven by 2 corpus cases and 3 real process owner tests; plan owner-map explicitly permits demonstrated owner changes — no alternate runner or caller bypass. Complete artifacts remain strict-decoded; malformed captured bytes and invalid real EOF still fail. Cost if wrong: diagnostic text behavior for truncated UTF-8 callers; covered by targeted owner tests and existing resilience regression.
- Task 6: Ruling: private worker transaction runs under existing caller-held candidate/round lock — public controller already holds that lock; acquiring it again would deadlock/conflict — concurrent tests use same canonical lock. Cost if wrong: private direct callers must honor the lock contract; method is internal and documented.
- Task 6: Ruling: preserve known 404/410 HTTP slot/body/hash/classification; existing transport exposes no physical retry receipt for these fail-fast statuses, so physical_retry_lineage remains null rather than fabricated — no new retry layer. Cost if wrong: unavailable physical lineage remains explicitly unknown.
- Task 7: Ruling: colocate immutable stable extract artifact with its original source snapshot in the existing candidate source store — same origin path persists across worker attempts; use the existing atomic immutable writer and proposal extract_ref, without a new extract registry — cost if wrong: later manifest validator must validate those source-store refs (existing reference policy already permits that root).
- Task 8: Ruling: use existing generic HostResponseReceipt/v1 for coverage stage; no new CoverageHostReceipt schema — approved wire families remain unchanged — cost if wrong: consumer must branch on coverage:<attempt> stage, not invent a receipt family (Task 10 public dispatch).
- Task 9: Ruling: keep existing store freeze/load transaction semantics — store freeze is create-only, so resume loads an existing exact pack or freezes only when absent — no new idempotent writer; cost if wrong: ambiguous pack state is rejected by canonical store/hash checks.
- Task 9: Ruling: source parser profile v2 triggers mandatory acquisition proof if mode artifacts are missing — it does not establish worker mode, which still requires real checkpoint v2 and manifest v3; source_run_id resolves the existing first-owner path — no native binding wire change; cost if wrong: a future independent v2 parser caller needs an explicitly reviewed provenance contract.
- Task 10: Ruling: resolve omitted host continuation run_id from existing canonical first-owner artifact — public protocol has no run_id and custom acquisition IDs must resume their actual owner; validate schema/candidate/round/seed before accepting that run — cost if wrong: stale first-owner artifact blocks rather than silently selecting a different run.
- Final: Ruling: first-acquisition provenance applies to canonical v1, existing retry v2/v3 uses its persisted authorization and actual bound parent proof — restore the existing pack-version owner boundary instead of fabricating a retry first manifest — cost if wrong: a retry must still be rejected if initial corpus proof is missing; explicit inherited/non-inherited retry and deleted-parent-proof tests enforce this.
- Final: Ruling: reviewer set aside real provider/scientific/performance acceptance — retain user Task 11 authorization gate, without claiming live readiness — cost if wrong: real provider compatibility, scientific recall and 30/60/90 behavior remain unverified.
- Final: Ruling: reviewer set aside whole upstream/dependency security audit — fixed-version related API/identity/diagnostics review is the authorized scope — cost if wrong: unrelated upstream/dependency vulnerabilities remain outside this review.
- Final: Ruling: reviewer set aside legacy/PDF redesign and unchanged semantic submission — retain existing contracts and run regression, do not expand implementation scope — cost if wrong: pre-existing bugs in those unchanged paths are not repaired here.
- Final: Ruling: reviewer set aside initial dirty/AGENTS/approved docs — retain exact baseline and attribute only this implementation — cost if wrong: earlier changes are preserved but not endorsed by this review.
- Final: Ruling: reviewer set aside full-suite pass without a terminal summary — interrupted progress is not completion; final post-fix run must supply actual terminal counts — cost if wrong: Task 10 delivery stays incomplete until that receipt exists.

## 最终状态和未验证边界

最终状态以 ledger 中 Final verification / Final gate / Final review 行为准：

- Final verification: full offline pytest 2089 collected / 2088 passed / 0 failed / 1 skipped / 2 warnings in 1715.85s, exit 0. Skipped: Windows symlink privilege unavailable. Warnings: existing transformers deprecated torch pytree registration. No new changes/failures/unresolved test concern justify another full run.
- Final gate: architecture/reuse PASS, allowed_to_proceed=true, violations=[]; two CLI helps exit 0; git diff --check exit 0; protected AGENTS/CLI/spec/plan baseline hashes unchanged; PaperQA2 pin clean and HEAD unchanged.
- Final review disposition: 0 Critical / 2 Important both fixed by TDD / 0 Minor; original single reviewer completed, no re-review. No confirmed architecture gap, no duplicate controller/config/serializer/retrieval/relevance path. Complete receipts retained without commit.
- Final remaining blocker: none within authorized offline Tasks 1-10. Windows symlink and actual concurrent junction replacement are not fully verified; live provider/scientific/performance evidence remains the separately gated Task 11.
- Final Task 11: NOT AUTHORIZED / NOT ATTEMPTED. Stop here; no live-corpus, Europe PMC, real embedding/summary or real 30-60-90 acceptance, no automatic implementation beyond Task 10.

**TASK_11 = NOT AUTHORIZED / NOT ATTEMPTED**。需要用户另行授权后，才可启动真实 live-corpus/Europe PMC/embedding/summary/30-60-90 acceptance；current-host cognition 必须由当前 Codex session 的 host-next/host-submit 完成，acceptance driver 只能 pause/resume，不能调用另一模型模拟 host。
