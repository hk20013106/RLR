# RLR Commit `7314039` 代码审查报告（中文版修订版）

- Repository：`https://github.com/hk20013106/RLR`
- Branch：`codex/hypothesis-ledger-cutover`
- Commit：`7314039ee4727ffbda3073607fad51a6d9c1ffd8`
- 审查日期：2026-07-30
- 文档定位：事故修复审查 + v0.9 收尾建议 + v1.0 迁移边界
- 补记日期：2026-08-01 —— 第 3 节 P1-1~P1-4、第 8 节 v0.9 清单已按分三批实施完毕，状态见各节内联标注与文末「实施结果补记」

---

## 1. 总体结论

`7314039` 有效封堵了一个已经实际发生的事故：

> 在 Claude Code 会话中运行 RLR 时，Deep Research 默认启动 Codex CLI，导致使用错误平台和错误额度。

本次修改中，以下方向正确：

1. host mismatch guard 位于 subprocess 之前；
2. `REQUIRED_DEPENDENCIES` 不再依赖 `engine.py` monkey-patch；
3. 增加 fresh-interpreter standalone import 测试；
4. Claude host 与 Codex backend 明确冲突时可以停止；
5. backend 字面量至少部分集中。

但该 commit 不能被描述为：

```text
完整的 host-agnostic runtime 已完成
```

更准确的表述是：

```text
已知事故路径已封堵
跨平台最终架构尚未完成
```

---

## 2. 本次 commit 应保留的修复

### 2.1 host mismatch guard 的执行顺序

正确顺序：

```text
读取 runtime
→ 判断 host mismatch
→ 检查 executable
→ 构建 invocation
→ 启动 subprocess
```

必须保持：

```text
任何已知 mismatch 都应在 quota-bearing executable 启动前终止
```

---

### 2.2 `REQUIRED_DEPENDENCIES` 所有权修复

当前将变量移入普通模块，解决 CLI 独立启动时的：

```text
NameError: REQUIRED_DEPENDENCIES is not defined
```

这是有效修复，不应回退。

长期可在 v1.0 迁入：

```text
core/dependencies/
```

但 v0.9 不必再做一次中间拆分。

---

### 2.3 fresh-interpreter 测试

使用新 Python 进程验证 import 和 CLI 行为，可以避免 pytest 当前进程中的既有 import 状态掩盖缺陷。

该类测试应继续保留，并在 v1.0 迁入：

```text
tests/contract/
```

---

## 3. v0.9 仍需修复的问题

### P1-1：runner 默认 Codex 仍可能覆盖项目 runtime — ✅ FIXED 2026-07-31

`run_loop.py` 仍保留类似：

```yaml
deep_research:
  backend: codex
  executable: codex
```

因此可能出现：

```text
preflight 检测 Claude
→ 项目 runtime 写入 Claude
→ automatic runner 再传 --backend codex
→ 项目配置被第二套配置覆盖
```

这是 v0.9 必须修复的问题。

最低修改：

- runner 默认不设置 backend；
- 没有显式 override 时，只读取项目 runtime；
- direct CLI 与 runner 共享同一 validator；
- runner 不再复制 `{codex, claude}` 字面量。

---

### P1-2：mixed runtime spec 可能通过 — ✅ FIXED 2026-07-31（`validate_spec_consistency()`）

例如：

```yaml
backend: claude
executable: codex
plugin_dir: C:/claude-plugin
```

仅比较：

```text
host == backend
```

无法证明实际 executable 正确。

v0.9 最低修复：

- backend 与 executable 明显冲突时停止；
- backend 切换时清理另一 backend 字段；
- Claude spec 不得保留 Codex `skill_path`；
- Codex spec 不得保留 Claude `plugin_dir`。

完整 adapter-level validation 放到 v1.0。

---

### P1-3：unknown host 当前行为不一致 — ✅ FIXED 2026-07-31（`host_matches(explicit=...)` + `RLR_HOST_BACKEND`）

配置创建时：

```text
unknown → fail-loud
```

运行时：

```text
unknown → permissive
```

这不一致。

v0.9 应改为：

```text
unknown + 无显式声明 → STOP
unknown + RLR_HOST_BACKEND 或 CLI 指定 → 允许
```

不需要现在实现复杂 host service，但不能静默继续。

---

### P1-4：缺少真正证明 subprocess 未启动的测试 — ✅ FIXED 2026-07-31（跨平台 sentinel fixture，`sys.executable` + 目录下名为 `exec` 的脚本，不依赖 `.cmd`）

当前测试主要检查：

- return code
- stderr

还需要 sentinel：

```text
fake executable 一旦启动就写文件
mismatch 运行结束后
sentinel 文件必须不存在
```

这才真正证明未消耗错误宿主额度。

---

## 4. 此前建议中需要撤回或延后的内容

### 4.1 暂不建立 `runtime/adapters/`

此前建议：

```text
runtime/adapters/
```

不应继续采用。

v1.0 的正式目标是顶层：

```text
adapters/
├── base.py
├── capabilities.py
├── resolver.py
├── host_detection.py
├── codex/
├── claude_code/
└── generic_cli/
```

如果 v0.9 先建立 `runtime/adapters/`，v1.0 还要再次迁移。

---

### 4.2 暂不建立完整 runtime 配置治理命令

此前建议：

```bash
rlr runtime configure
rlr runtime show
rlr runtime verify
```

功能上合理，但其最终 schema 会受到以下内容影响：

- adapter registry
- machine capability registry
- generated distributions
- MCP transport
- AI4AI optimization contract

因此这些命令应在 v1.0 统一设计，而不是基于旧 `RuntimeSpec.backend` 做长期接口。

v0.9 只要求：

- preflight 报告实际配置；
- 不静默忽略 backend 参数；
- 错误配置停止；
- runner 与 CLI 共享验证逻辑。

---

### 4.3 不再要求 legacy 模块全面补到 80%

如果 `deep_research.py`、`run_loop.py`、`common.py` 将在 v1.0 重构，单纯为旧结构补大量测试的收益有限。

调整为：

```text
v0.9：事故路径与新增逻辑强制覆盖
v1.0：新 core/adapters/workflows 严格 coverage gate
```

这不等于放弃测试，而是避免把测试投资锁定在即将删除的结构上。

---

### 4.4 不把 MCP 加入 `SUPPORTED_BACKENDS`

Literature Search MCP 提供的是文献发现能力：

```text
search
normalize
deduplicate
RRF
source status
```

它不是 Claude 或 Codex 这样的执行宿主。

因此禁止：

```python
SUPPORTED_BACKENDS = ("codex", "claude", "mcp")
```

正确设计：

```text
invoking_host
execution_adapter
research_transport
```

MCP 应作为：

```text
research_transport = literature_search_mcp
```

进入 v1.0。

---

## 5. MCP 对当前修复建议的影响

MCP 文献管线将拆为：

```text
QueryPlanner
→ Crawler / MCP
→ Selector
→ Evidence Extractor / Verifier
```

因此以下旧逻辑不值得在 v0.9 深度重构：

- search 与 extract 混合 invocation；
- 单一 `backend` 负责全部研究能力；
- 将 skill path 作为文献检索唯一入口；
- 在 `deep_research.py` 中继续增加更多 provider 分支。

但以下安全边界仍必须保留：

- DOI/PMID/稳定 URL 独立过滤；
- rejected-record audit；
- abstract 不得冒充 section evidence；
- 真实上游 metadata 不得伪造；
- 零条可验证记录时 fail-closed；
- receipt 与 run ID 精确绑定。

这些规则属于 RLR core，不依赖 MCP 或宿主。

---

## 6. AI4AI 对当前修复建议的影响

v1.0 很可能加入 AI4AI 最小治理层，包括：

- `OptimizationContract/v1`
- 系统优化实验账本
- 隔离评估集
- 资源预算
- 接受/拒绝/升级规则
- 禁止优化器修改自己的 evaluator 和 threshold

因此，以下内容不应在 v0.9 临时分散实现：

- 多套自行演化的 prompt 优化逻辑；
- 自动修改 gate 阈值；
- 将系统优化记录写入科学假设账本；
- 允许 agent 自己定义成功标准；
- 无版本记录的 selector/query planner 调整。

v0.9 只保持行为稳定并记录现状；优化治理放到 v1.0。

---

## 7. v1.0 的正式目标架构

```text
src/research_loop/
├── core/
│   ├── state_machine/
│   ├── schemas/
│   ├── gates/
│   ├── artifacts/
│   ├── context/
│   ├── provenance/
│   ├── dependencies/
│   └── degradation.py
│
├── workflows/
│   ├── L0/
│   ├── L1/
│   ├── ...
│   └── L10c/
│
├── adapters/
│   ├── base.py
│   ├── capabilities.py
│   ├── resolver.py
│   ├── host_detection.py
│   ├── codex/
│   ├── claude_code/
│   └── generic_cli/
│
├── research/
│   ├── discovery/
│   ├── selection/
│   ├── extraction/
│   ├── verification/
│   └── transports/
│       ├── literature_mcp/
│       ├── native_skill/
│       └── direct_api/
│
└── optimization/
    ├── contracts/
    ├── ledger/
    ├── evaluators/
    └── experiments/

distributions/
├── codex/
└── claude_code/

tests/
├── contract/
├── parity/
├── core/
├── adapters/
├── research/
└── optimization/

scripts/
└── build_distributions.py
```

---

## 8. 修订后的实施顺序

### v0.9（实施状态，2026-08-01 补记）

1. 删除 runner 默认 Codex。—— ✅ 已完成
2. mixed spec fail-closed。—— ✅ 已完成
3. unknown host 要求显式声明。—— ✅ 已完成
4. sentinel 测试。—— ✅ 已完成
5. Windows + Ubuntu CI。—— ⚠️ **范围变更**：只做了 windows-latest，ubuntu 被用户明确取消，未做跨平台修复；Linux 兼容性目前无 CI 验证
6. 文献候选逐条过滤。—— ✅ 已完成（本次三批之前的提交中已实现，三批只补了文档对齐）
7. 冻结发布。—— 未执行冻结/打 tag 动作；发布门 checklist 已全部勾选（除已知非阻断项），是否正式冻结待用户决定

### v1.0

1. 建立 core 边界。
2. 建立顶层 adapters。
3. 建立 canonical workflows。
4. 把 MCP 作为 research transport。
5. 拆分 QueryPlanner/Crawler/Selector/Extractor/Verifier。
6. 建立 generated distributions。
7. 建立 contract/parity tests。
8. 加入 AI4AI 最小治理层。
9. 删除 v2.0 compatibility profile 和 legacy read path。
10. 完成迁移后再删除旧单体模块。

---

## 9. 最终判定

`7314039` 应保留为：

> 有效的事故热修复。

但后续不应继续在其当前结构上堆叠 MCP、AI4AI 和更多 backend 分支。

正确路线是：

```text
v0.9 完成最低必要收尾
→ 冻结
→ v1.0 按 core/workflows/adapters/research/optimization/distributions 重构
```

---

## 10. 实施结果补记（2026-08-01）

P1-1 ~ P1-4 四项已全部修复，代码落在 `codex/hypothesis-ledger-cutover` 分支（未 push 到 main）：

- P1-1、P1-2：`src/run_loop.py`、`src/research_loop/deep_research.py`（`validate_spec_consistency()`）
- P1-3：`deep_research.py` 的 `host_matches()` 新增 `explicit` 参数 + 新增 `RLR_HOST_BACKEND` 环境变量
- P1-4：`tests/test_deep_research.py` 新增跨平台 sentinel fixture

第 8 节 v0.9 实施顺序 1–4、6 已完成，7（冻结）未执行。第 5 项（跨平台 CI）**范围被用户中途收窄为 windows-only**——首次跑全矩阵时 ubuntu 单独暴露一个依赖 Windows `.cmd` 的测试失败，用户直接决定取消 ubuntu，不是修复后仍保留双平台。这意味着本报告第 1 节结论中"跨平台最终架构尚未完成"这句话，在 CI 验证范围这个层面，v0.9 收尾后依然成立——只是现在连 Linux 的自动化验证都没有了，而不是"已验证但未完全实现"。

测试与 coverage 真实数字、CI 三轮迭代的具体日志摘要，见 `docs/releases/v0.9-verification.md`；发布门勾选见 `docs/v0.9-implementation-plan.md`。
