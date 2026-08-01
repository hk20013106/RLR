# Literature Search MCP 集成方案（草案 v0.1）

> 状态：**有待改进的方案**，尚未实施。
> 来源：`literature-search-mcp-source-v1.0.0.zip`（Apache-2.0，Node.js 22 stdio MCP server）。
> 日期：2026-07-29。

## 1. 这个 MCP 是什么

**Literature Search MCP** —— 一个独立的 stdio MCP server，对外暴露两个 tool：

| Tool | 作用 |
|---|---|
| `literature_search` | 并行检索 7 个学术元数据源，归一化 → 去重 → Reciprocal Rank Fusion（k=60）→ 返回排序结果 |
| `literature_sources` | 列出源的可用性、凭据状态和限制 |

**覆盖的 7 个源**（固定处理顺序）：

1. PubMed（NCBI E-utilities）
2. Europe PMC
3. bioRxiv / medRxiv
4. Crossref
5. OpenAlex
6. Semantic Scholar
7. arXiv

**返回字段**：`title`, `abstract`（截断）, `identifiers`（DOI/PMID/PMCID/arXiv/OpenAlex/S2/biorxiv）, `url`, `pdf_url`, `year`, `authors`, `venue`, `open_access`, `source_evidence`, `fused_score`, `source_statuses`。

**输入参数**：`query`（必填）, `limit`(1–50), `sources`（子集）, `year_from`/`year_to`, `open_access`。

**不返回**：全文、引用图谱、按 section 定位的证据摘录（Results / Discussion / Methods 等）。

**无 API key 即可运行**；可选环境变量（`NCBI_API_KEY`, `OPENALEX_MAILTO`, `SEMANTIC_SCHOLAR_API_KEY`, `CROSSREF_MAILTO` 等）提升限额。

**自带离线测试**：`npm test`（`node:test` + fixtures + fake fetch），`npm run test:live` 可选。

---

## 2. RLR 现状

### 2.1 文献检索发生在哪

RLR 的文献检索在 3 个 pre-research 节点触发，由 `deep_research.py` 驱动：

| 节点 | 类型 | 要求 |
|---|---|---|
| L1 | `deep_research` | 每篇论文有 located Results / Discussion / Conclusion extract |
| L4 | `literature_review` | 有 located Methods extract + review search receipt |
| L8.5 | `literature_verification` | 有 paper-based verification verdict + evidence_ids |

### 2.2 当前执行方式

`deep_research.py` 的 `build_invocation` 构建命令：

- **Codex backend**：`codex exec --output-schema <schema> $academic-research-suite`
- **Claude backend**：`claude -p --plugin-dir <dir> --json-schema <schema> /ars-full`

然后 `subprocess.run(command + [prompt])`，期望 stdout 返回符合 schema 的 JSON evidence。

`validate_payload` 校验：每条保留的论文候选至少需 DOI、PMID 或稳定 URL 之一，并继续满足 `source_metadata_response` + `extracts`（含 section/text/locator）。`audit_evidence_pack` 进一步校验 section 级别要求。

### 2.3 核心问题

`RLR_V05B_README.md` 自述：`academic-research-suite` 只是 prompt 文本里 "named only"，没有代码实际调用/检查。`deep_research.py` 虽然构建了 CLI 命令并 subprocess 执行，但：

- 依赖 Codex CLI / Claude CLI + 特定 skill 安装，脆弱
- 不可离线测试（需要外部 CLI 可用）
- skill 是否真的被调用不可验证
- 整条链 search + extract 混在一起，单一失败点

---

## 3. 对齐分析

| 维度 | MCP 提供 | RLR 需要 | Gap |
|---|---|---|---|
| 多源并行搜索 | ✅ 7 源 | ✅ | 无 |
| 去重 + 排序 | ✅ RRF | 未要求特定排序 | 无 |
| DOI / PMID / URL | ✅ | ✅ | 无 |
| Abstract | ✅ 截断摘要 | 用于初步筛选 | 无 |
| PDF URL | ✅ `pdf_url` | 可用于后续全文获取 | 无 |
| `source_statuses` | ✅ | 可作为 tool receipt | 无 |
| **全文 section 摘录** | ❌ 不下载全文 | ✅ Results/Methods/Discussion | **核心 gap** |
| **`source_metadata_response`** | ❌ 返回归一化结果 | ✅ 要原始 API 响应 | 仍需补真实上游响应，不得从归一化字段拼造 |
| **review search receipt** | ❌ | ✅ L4 要 | 需补 |
| **verification verdict** | ❌ | ✅ L8.5 要 | 需补 |

**结论**：MCP 完整覆盖**发现层**（search → 候选论文列表 + 元数据），但不覆盖**证据提取层**（全文 section 定位摘录）。候选列表必须经过 Research Loop 统一的逐条标识符过滤和 rejected-record audit；这不是放宽证据要求。

---

## 4. 集成方案：两阶段拆分（路径 B）

```
当前:  codex/claude CLI + $academic-research-suite  →  JSON evidence (search + extract 混在一起)

改后:  阶段 1 — MCP literature_search          →  候选论文列表 (DOI/abstract/URL/source_evidence)
       阶段 2 — 全文获取 + section 定位摘录      →  located extracts (Results/Methods/Discussion)
```

### 4.1 阶段 1：MCP 作为发现 backend

**改动文件**：`src/research_loop/deep_research.py`

1. **新增 `mcp` backend**
   - `RuntimeSpec.backend = "mcp"`, `executable = "node"`, `skill_path = dist/server.js 绝对路径`
   - `default_runtime_config()` 增加 mcp 选项
   - `runtime_ready()` 增加 mcp 检查：`node --version` ≥ 22 + `dist/server.js` 存在

2. **`build_invocation` 增加 mcp 分支**
   - spawn `node dist/server.js`，通过 JSON-RPC（stdio）调 `literature_search`
   - 搜索查询来自 `PRE_RESEARCH_MAP` 的 seed queries + candidate question/claim
   - `sources` 可按节点配置（如 L1 侧重 PubMed/EuropePMC/OpenAlex，L8.5 侧重 PubMed/EuropePMC）

3. **适配统一候选过滤与 `validate_payload`**
   - MCP 结果先把 `identifiers`、`url`、`source_evidence`、`source_statuses` 归一化为 Research Loop 的候选记录；不能假定每条结果都有 DOI/PMID/URL
   - 逐条检查 DOI、PMID、稳定 URL；三者均缺失的记录从可用证据集合剔除，并写入 rejected-record audit（原始序号、标题、标识符当前值、原因、backend、run ID）
   - 至少一条候选通过标识符检查时，继续 metadata、extract、evidence pack 和 audit；全部不合格或没有可验证候选时才 fail-closed
   - `source_metadata_response` 只能来自真实上游响应，不能用归一化字段拼造；`extracts` 不能以 abstract 冒充 L1/L4/L8.5 所要求的 section-level evidence（见 4.3）

4. **`skill_receipt` 增加 mcp 记录**
   - backend=`mcp`, skill=`literature-search-mcp`, skill_version 从 package.json 读
   - command_hash / prompt_hash 照常

5. **查询历史**
   - MCP 自带 `history.jsonl`（`~/.local/state/literature-search-mcp/`）
   - RLR 的 `persist_run` 已有自己的 run artifact，两者互补

### 4.2 阶段 2：全文证据提取（可后续迭代）

有了 MCP 的结构化候选列表（含 `pdf_url` / `url`），提取变得简单：

- 用 `pdf_url` + `web_extract` 获取全文（优先 OA）
- Unpaywall fallback（用 DOI 查 OA 全文）
- 按 section heading 切割，定位 Results / Methods / Discussion / Conclusion
- 生成符合现有 `extracts` schema 的 located evidence

**这一步是 MCP 之外的工作**，但有了阶段 1 的结构化输入，实现简单且可独立测试。

### 4.3 L1/L4 section 要求的过渡策略

MCP 只给 abstract。两个选择：

- **禁止方案**：不得把 abstract 当作 Results/Methods/Discussion/Conclusion，也不得为 `mcp` backend 增加宽松校验路径来降低 `validate_payload` / `audit_evidence_pack` 的证据门。
- **采用方案**：阶段 2 实现全文获取和 section 定位后再接入，保持现有 L1/L4/L8.5 section 要求不变。

在全文 section 证据可用前，MCP 只能作为候选发现层；过滤不可验证候选不等于放宽证据要求。

### 4.4 离线测试

- MCP 自带 `node:test` 离线测试套件（HTTP behavior / provider parsers / aggregation / dedup / history / MCP tool registration）
- RLR 可 mock MCP 返回（fixture JSON）测试 `validate_payload` 和 `persist_run`
- `runtime_ready` 的 mcp 检查可离线测试（不发起网络请求）

---

## 5. 路径 B 的优势

1. **解决核心痛点**：从 "named only" 变成代码级调用，有真实 receipt
2. **可离线测试**：MCP 有完整 offline test，RLR 可用 fixture 测试整条链
3. **消除外部依赖**：不需要 Codex CLI / Claude CLI / academic-research-suite skill 安装，只要 Node.js 22
4. **保持证据链**：section 摘录需求不丢，只是拆到独立步骤
5. **渐进式**：先接 MCP 做发现（abstract 级别证据），全文提取可后续迭代

---

## 6. 有待决定的问题

1. **L1/L4 的 section extract 要求**：MCP 只给 abstract。是先放宽到 abstract-level evidence，还是同时实现全文提取步骤？
2. **MCP 安装位置**：解压到 `D:\Programs\literature-search-mcp` 还是项目内 `tools/` 下？MCP 注册后路径不能移动。
3. **可选 API key**：是否配置 `NCBI_API_KEY` / `OPENALEX_MAILTO` 等？无 key 也能用，只是限速。
4. **sources 子集策略**：各节点是否限定搜索源子集？如 L1 侧重 PubMed/EuropePMC/OpenAlex，L8.5 侧重 PubMed/EuropePMC。
5. **与现有 codex/claude backend 的关系**：mcp 是替代还是并列选项？`deep_research_runtime.json` 是否支持多 backend 切换？
6. **阶段 2 的优先级**：全文 section 提取是 v0.9 还是更后面？

---

## 7. MCP 安装与注册（参考）

来源 ZIP：`literature-search-mcp-source-v1.0.0.zip`

```bash
# 解压到永久目录
mkdir -p ~/tools
unzip literature-search-mcp-source-v1.0.0.zip -d ~/tools
cd ~/tools/literature-search-mcp

# 安装依赖 + 构建
npm ci
npm run typecheck
npm test
npm run build

# 验证
node dist/server.js   # 启动 stdio server，Ctrl+C 退出
```

构建产物：`dist/server.js`（stdio 入口）、`dist/cli.js`（history clear）。

MCP client 启动命令等价于：
```json
{ "command": "node", "args": ["/absolute/path/to/dist/server.js"] }
```

可选环境变量：
```text
OPENALEX_MAILTO
OPENALEX_API_KEY
SEMANTIC_SCHOLAR_API_KEY
CROSSREF_MAILTO
NCBI_TOOL
NCBI_EMAIL
NCBI_API_KEY
```

查询历史：`${XDG_STATE_HOME:-~/.local/state}/literature-search-mcp/history.jsonl`

---

## 8. 文件索引

| 文件 | 作用 |
|---|---|
| `src/research_loop/deep_research.py` | Deep Research runtime + evidence pack + audit（主要改动点） |
| `src/research_loop/commands/research.py` | `cmd_deep_research_run` 入口 + pre-research prompt 生成 |
| `src/research_loop/preresearch.py` | `PRE_RESEARCH_MAP`（L1/L4/L7/L8.5 配置）+ provenance 校验 |
| `src/research_loop/commands/ledger.py` | L0 依赖检查（含 `academic-research-suite` skill 路径检查） |
| `src/manage_literature_db.py` | 文献数据库 CRUD（add/sync，DOI/title 去重） |
| `docs/MAIN_AGENT_RUN.md` | 主 agent 运行协议（含 deep-research-run 说明） |
| `docs/RLR_V05B_README.md` | 自述问题："Is `academic-research-suite` really invoked? Named only." |

---

## 9. 前置约束：backend 必须宿主无关（2026-07-30 新增）

本计划第 172 行的开放问题"mcp 与现有 codex/claude backend 是并列还是替代、`deep_research_runtime.json` 是否支持多 backend 切换"，在真实数据验证中已暴露为实际缺陷，需在 MCP 接入前解决。

### 已确认的实现事实

- `deep_research.py:45-47` 的 `default_runtime_config()` 硬编码 `backend`/`executable` 为 `codex`，`skill_path` 指向 `~/.codex/skills/academic-research-suite`，不检测当前宿主；
- `lifecycle.py:645` 项目 init 无条件写入该默认值；
- `deep_research.py:191-192`、`768-769` 与 `cli.py:410` 的 backend 集合被写死为 `{codex, claude}`；
- `providers/headless.py:41-46` 已有 `CLAUDECODE`/`CLAUDE_CODE` 宿主探测，deep-research 层未复用。

后果：在 Claude 会话中运行 RLR，deep-research 默认调用 Codex CLI，消耗错误宿主的额度。

### 对 MCP 接入的约束

1. 新增 `mcp` backend 前必须先把 backend 白名单改为**可注册表**。否则每加一个 backend（mcp、AntiGravity、Hermes）都要改 `deep_research.py` 的两处校验分支和 `cli.py` 的 choices，扩散成本随 backend 数线性增长。
2. `mcp` 是**并列选项**，不是替代：MCP 只承担 discovery，宿主 agent 仍承担 extract/verify。因此 runtime config 需同时表达"用哪个宿主执行 agent"和"用哪个 backend 做检索"，两者是独立维度，不能挤在单个 `backend` 字段里。若继续沿用单字段，`backend=mcp` 会丢失宿主信息。
3. 宿主选择必须来自当前会话检测（扩展 `providers/headless.py` 的探测），检测失败时 fail-loud 要求显式指定，不得静默回落 Codex。
4. `skill`/`skill_path`/`plugin_dir`/`upstream`（`deep_research.py:240-242`）必须随宿主派生，不以 Codex 布局为默认。
5. 统一边界不变，与第 4.1 节及 `docs/v0.9-implementation-plan.md` 的过滤规则一致：DOI/PMID/稳定 URL 校验、rejected-record audit、evidence receipt、fail-closed 由 RLR 执行，与宿主和检索 backend 均无关。

### 实施结果与范围修正（2026-07-30）

范围决定：v0.9 只支持 `{codex, claude}`，AntiGravity/Hermes 不纳入。因此**上文第 1 条「先把 backend 白名单改为可注册表」作废** —— 白名单保持封闭，但已收敛为单一常量 `deep_research.SUPPORTED_BACKENDS`，`build_invocation`、`runtime_ready`、`cli.py` 三处不再各写各的字面量。将来若确定新增 backend，改动面是这一个常量加对应分支，而非四处散落的字面量。

已落地（宿主维度，对应第 3、4 条）：

- `detect_host_backend(env=None)` 按 `_HOST_MARKERS` 探测当前宿主，探测不到返回 `None`；
- `default_runtime_config(backend=None, env=None)` 按宿主派生配置，探测不到时 fail-loud 要求 `--backend`，不再静默回落 Codex；
- `host_matches(spec, env=None)` + `cmd_deep_research_run` 中的宿主一致性门，在任何 subprocess 之前拦下跨宿主运行，`--allow-host-mismatch` 显式放行；
- `skill_path`/`plugin_dir` 随 backend 派生；claude 的 `plugin_dir` 留空由 `runtime_ready` 报缺失，不臆造安装路径。

已知限制：Codex 环境标记未在真实 Codex 会话中验证，`_HOST_MARKERS` 目前只登记 Claude Code 的 `CLAUDECODE`/`CLAUDE_CODE`。

**仍为 MCP 接入前置依赖**：上文第 2 条（"用哪个宿主执行 agent" 与 "用哪个 backend 做检索" 是两个独立维度，不能挤在单个 `backend` 字段）**未解决**。当前 `RuntimeSpec.backend` 仍是单字段，直接加 `backend=mcp` 会丢失宿主信息，并使刚建立的宿主一致性门失效 —— `host_matches` 会把 `mcp` 判为与宿主不符而误拦。阶段 1 之前必须先拆开这两个维度。

第 5 条（统一证据边界与宿主、检索 backend 均无关）不变。

验证：`python -m pytest -q` → 392 passed；覆盖率 TOTAL 68%（未下降）。详见 `docs/releases/v0.9-verification.md`。
