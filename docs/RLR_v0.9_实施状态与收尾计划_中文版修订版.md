# RLR v0.9 实施状态与收尾计划（中文版修订版）

- 最后更新：2026-08-01（补记：v0.9 收尾三批已实施完毕，详见文末「实施结果补记」）
- 版本定位：过渡版、风险收尾版
- 下一版本：v1.0
- 核心原则：v0.9 不再承担完整架构重构，只完成必须的事故封堵、数据正确性保护和可回归验证

---

## 1. 版本定位

v0.9 的任务不是建立最终的跨平台架构，而是：

1. 封堵当前已经发生或已经确认的错误执行路径；
2. 保证现有 v2.1 工作流能够稳定完成；
3. 为 v1.0 重构留下清晰边界；
4. 避免在即将被替换的旧模块上投入过多重构成本。

因此，以下两类工作必须区分：

```text
v0.9：最低必要修复
v1.0：正式架构重构
```

v0.9 不应继续扩张 `deep_research.py`、`run_loop.py`、`common.py` 等大模块，也不应为了短期兼容新增另一套临时 runtime 架构。

---

## 2. 已完成范围

已纳入并完成：

- `v2.1-catalog-1` profile
- YAML persona catalog
- profile-aware L8
- L9a → L9b 串行门
- Curie L1/L4 pre-research receipt
- EvidenceRunReceipt/v1.1 精确绑定
- ContextManifest/v2
- RunReceipt/v1
- candidate-scoped Obsidian/report consumer
- CLI `check-deps` 的 `NameError` 修复
- Claude Code 会话误启动 Codex CLI 的已知事故路径封堵

当前状态：

| 项目 | 状态 |
|---|---|
| v2.1 profile、receipt、context、L8/L9 路径 | ✅ 完成 |
| CLI `REQUIRED_DEPENDENCIES` 所有权错误 | ✅ 已修复 |
| 已知 Claude-host / Codex-executable 事故路径 | ✅ 已封堵 |
| 最低限度 runtime 安全检查 | 🟡 需补强 |
| 文献候选逐条过滤 | 🟡 只做最低必要修复 |
| 全量 80% coverage | ⏸ 不再作为 v0.9 硬门 |
| 完整 adapter 架构 | ➡️ 转入 v1.0 |
| MCP 文献管线 | ➡️ 转入 v1.0 |
| AI4AI 优化治理 | ➡️ 转入 v1.0 |

---

## 3. v0.9 仍然必须完成的发布阻断项

### 3.1 删除 automatic runner 的默认 Codex 覆盖

当前最危险的剩余问题是：

```text
项目 runtime 可能已经检测为 Claude
但 run_loop.py 仍使用默认 Codex 配置
```

v0.9 必须做到：

- `run_loop.py` 不再默认写入 `backend=codex`
- 没有显式 override 时，runner 使用项目已有 runtime
- runner 不再独立维护一套 backend 白名单
- direct CLI 与 automatic runner 的最终执行结果一致

最低验收测试：

```text
Claude 项目 runtime + runner 无 override
→ 不得调用 Codex

Codex 项目 runtime + runner 无 override
→ 使用 Codex

runner 明确指定不同宿主
→ 必须 fail-closed 或要求显式 override
```

---

### 3.2 mixed runtime spec 必须 fail-closed

以下配置不得通过：

```yaml
backend: claude
executable: codex
skill_path: ~/.codex/skills/...
```

v0.9 不需要建立完整 adapter registry，但必须增加最低限度的一致性校验：

- Claude runtime 不得继承 Codex `skill_path`
- Codex runtime 不得继承 Claude `plugin_dir`
- backend 切换时必须清理另一 backend 的字段
- executable 与 backend 明显冲突时必须停止

这里的目标只是阻止错误 CLI 被启动，不是完成 v1.0 的最终 runtime 模型。

---

### 3.3 unknown host 不得静默放行

当前宿主识别失败时，不应继续执行持久化 runtime 中的旧 backend。

v0.9 最低策略：

```text
检测到 Claude marker → Claude
检测到明确 Codex marker → Codex
检测不到 → 要求显式指定
```

允许增加：

```text
RLR_HOST_BACKEND=claude
RLR_HOST_BACKEND=codex
```

但不要求在 v0.9 中实现完整的 host detection service。

---

### 3.4 增加 subprocess sentinel 测试

必须有测试证明：

```text
host mismatch
→ executable 完全没有被启动
→ sentinel 文件不存在
→ 不生成成功 receipt
```

仅检查错误码和错误文字不够。

该测试应使用 Python 脚本配合 `sys.executable`，不要只依赖 Windows `.cmd`，以便同时运行在 Windows 与 Ubuntu。

---

### 3.5 保留最低限度跨平台 CI

v0.9 最低 CI：

```text
Windows
Ubuntu
Python 3.11
Python 3.12
```

v0.9 不要求每个平台所有高级功能完全 parity，但必须验证：

- import
- CLI help
- preflight
- runtime mismatch guard
- sentinel
- standalone dependency check
- 当前核心 test suite

---

## 4. 文献候选过滤：v0.9 只做最低必要修复

现有问题是：

```text
一条记录没有 DOI/PMID/稳定 URL
→ 整批结果失败
```

v0.9 仍应修复这一明显的数据处理缺陷，但不要在旧 `deep_research.py` 中建设完整 MCP discovery 架构。

最低行为：

1. 对每条候选独立检查 DOI、PMID、稳定 URL；
2. 不合格记录进入简单 rejected-record audit；
3. 至少一条合格记录时继续；
4. 全部不合格时 fail-closed；
5. abstract 不得冒充 Results、Methods、Discussion 或 Conclusion；
6. 归一化字段不得伪造 `source_metadata_response`。

最低审计字段：

```json
{
  "run_id": "...",
  "record_index": 3,
  "title": "...",
  "doi": null,
  "pmid": null,
  "url": null,
  "reason": "missing_stable_identifier"
}
```

以下内容不在 v0.9 完成：

- MCP discovery receipt
- QueryPlanner
- Selector
- 引用链扩展
- RRF 与 relevance score 分离
- 完整全文提取管线
- AI4AI 检索优化实验

这些统一进入 v1.0。

---

## 5. v0.9 不再要求完成的工作

### 5.1 不再要求完整 `runtime configure/show/verify`

此前建议增加：

```bash
rlr runtime configure
rlr runtime show
rlr runtime verify
```

该方向合理，但将在 v1.0 adapter architecture 中重新设计。

v0.9 只需：

- preflight 能报告当前 runtime；
- direct CLI 与 runner 使用相同验证函数；
- 错误配置停止执行；
- 不静默改写已有 runtime。

---

### 5.2 不再要求建立临时 `runtime/adapters/`

v0.9 不应创建：

```text
runtime/adapters/
```

因为 v1.0 的正式结构是：

```text
adapters/
├── base.py
├── capabilities.py
├── resolver.py
├── codex/
├── claude_code/
└── generic_cli/
```

v0.9 新增代码应尽量小，避免形成第二套过渡架构。

---

### 5.3 不再要求旧代码全量达到 80% coverage

旧计划要求：

```text
TOTAL coverage ≥ 80%
```

但 v1.0 将迁移和拆分大量旧模块，对即将替换的 legacy 代码强行补到 80%，成本与价值不匹配。

v0.9 改为：

- 所有事故路径必须有回归测试；
- 所有新增代码必须有测试；
- runtime guard、文献过滤、receipt、runner 路径必须覆盖；
- 不允许 coverage 明显下降；
- CI 中记录真实 coverage；
- v1.0 新架构模块再执行严格 coverage 门。

建议 v1.0 门槛：

```text
core/adapters/workflows 新模块 ≥ 85%
全仓库 ≥ 80%
关键安全模块分支覆盖 ≥ 90%
```

---

### 5.4 不在旧 backend 字段中增加 `mcp`

禁止：

```yaml
backend: mcp
```

原因是 MCP 不是宿主 agent。

正确区分：

```text
invoking_host      = claude_code / codex
execution_adapter  = claude_code / codex / generic_cli
research_transport = literature_mcp / native_skill / api
```

MCP 在 v1.0 中作为 `research_transport` 接入。

---

## 6. v0.9 最终发布门

- [x] runner 不再默认覆盖为 Codex
- [x] mixed runtime spec fail-closed
- [x] unknown host 无显式声明时停止
- [x] mismatch sentinel 证明 subprocess 未启动
- [x] ~~Windows + Ubuntu~~ **Windows-only** CI 通过（范围变更，见第 9 节）
- [x] 文献候选逐条过滤完成（`_filter_unidentifiable_papers`，先前提交实现，本次三批只补文档）
- [x] 全部不合格时 fail-closed
- [x] abstract 不得绕过 section evidence 门（先前提交实现，未在本次三批改动）
- [x] `source_metadata_response` 不得伪造（先前提交实现，未在本次三批改动）
- [x] 当前完整测试套件通过 — `404 passed, 0 failed`
- [x] coverage 结果写入 release verification — `docs/releases/v0.9-verification.md`，`64%`（`--cov=src`）
- [x] 文档明确：v0.9 仅为双宿主安全收尾，不是最终跨平台架构

未完成项（均为已知、非阻断，转入独立收尾或 v1.0）：

- [ ] `claim >-` YAML 解析 bug
- [ ] Codex 环境标记在真实 Codex 会话中验证（`_HOST_MARKERS` 只登记 Claude；`RLR_HOST_BACKEND` 是临时替代）
- [ ] Linux（Ubuntu）CI 覆盖 —— 见第 9 节，第一次全矩阵跑就暴露一个 Linux-only 失败，用户决定直接取消 ubuntu，未做跨平台修复
- [ ] 80% coverage（本已非硬门，纯记录项）

证据与详细数字见 `docs/releases/v0.9-verification.md` 与 `docs/v0.9-implementation-plan.md`。

---

## 7. v0.9 之后立即进入 v1.0

v1.0 的核心工作：

```text
core/
workflows/
adapters/
research transports/
distributions/
contract tests/
parity tests/
AI4AI governance/
```

v0.9 中所有临时修复必须遵守两个约束：

1. 不继续扩大 legacy 单体模块；
2. 不阻碍 v1.0 按目标架构迁移。

---

## 8. 最终结论

v0.9 的正确定位是：

> 封堵事故、保证正确、留下迁移边界。

不应把 v0.9 变成一次不完整的 v1.0 架构重构。

完成最低必要修复后，应冻结 v0.9，并把 MCP、AI4AI、adapter registry、canonical workflows 和 generated distributions 统一放入 v1.0。

---

## 9. 实施结果补记（2026-08-01）

本文档第 3 节的 5 个发布阻断项（3.1–3.5）已按分三批实施完毕，全部在 `codex/hypothesis-ledger-cutover` 分支，未 push 到 main：

- 3.1 runner 不再默认 Codex — 已实现
- 3.2 mixed runtime spec fail-closed — 已实现
- 3.3 unknown host 不得静默放行 — 已实现（新增 `RLR_HOST_BACKEND` 环境变量作为显式声明逃生口）
- 3.4 subprocess sentinel 测试 — 已实现（跨平台，`sys.executable` + 目录下名为 `exec` 的脚本，不依赖 `.cmd`）
- 3.5 跨平台 CI — **部分实现，范围已变更**：原计划 Windows + Ubuntu，实施中途用户决定取消 Ubuntu，最终只有 `windows-latest × {3.11, 3.12}`。CI 首次真正跑通前迭代了 3 轮，修的都是仓库此前零 CI 从未暴露过的既有环境缺陷（缺 `pandas`/`scipy` 依赖声明、Windows 短路径别名导致的测试断言问题），与本次三批的宿主门改动本身无关。**Linux 兼容性目前没有任何自动化验证**，是本次遗留的真实缺口，不是笔误。

第 4 节的文献候选过滤最低行为，在本次三批之前的提交中已经实现（`deep_research.py:333` 等），三批本身只补了文档对齐，没有重写逻辑。

未完成、明确转为独立收尾项或 v1.0 范围：`claim >-` YAML 解析 bug、Codex 环境标记验证、Linux CI 覆盖、80% coverage（已降级为非硬门记录项）。

详细改动、真实测试数字（`404 passed, 0 failed`，coverage `64%`）、CI 三轮迭代记录，见 `docs/releases/v0.9-verification.md`；发布门 checklist 的机器可读版本见 `docs/v0.9-implementation-plan.md`。
