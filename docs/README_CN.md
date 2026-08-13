# Research Loop Room (RLR) — 研究循环室

[English](../README.md) | **中文**

---

## 这是什么

RLR（Research Loop Room）是一套**证据门禁 + 多角色隔离 + 可追溯执行**的科学研究框架。

一个研究问题进入 RLR 后，会依次经过 **15 个正式 DAG 节点（L0 → L10c）**。这些节点由 **10 个角色（persona）**分工完成：提出假设、批判假设、筛选、方法设计、方法审查、执行代码、结果审计、文献核验、证伪、生物学解释、价值判断和最终决策。

它的核心不是“让很多 AI 一起聊天”，而是：

- 每个认知角色只看到 DAG 允许它看到的信息；
- 文献检索必须留下可验证 evidence pack，而不是手写摘要；
- 科学数据在进入执行层前必须明确授权并绑定 hash；
- **只有 L7 图灵（Turing）可以执行代码**；
- 软件维护（Meta-RLR）在科学 DAG 之外，不能成为第二套科学状态系统。

> **核心原则：**认知角色通过“信息不可见”实现隔离（Path B）；Turing 通过受控 workspace + 命令边界实现执行隔离（Path A）。RLR 不把 agent 进程假装成操作系统沙箱。

## 当前 main 状态

当前 `main` 已经包含经过验证的 **V0.9 / native-v2.1 架构线**。

新项目默认绑定：

`v2.1-catalog-1`

PR #16 之后进入 main 的关键变化包括：

- **PR #16 — Round Data Continuity：**跨轮数据不再靠模糊目录或 `input_manifest.md` 传递，而是通过 `L0EvidenceBinding/v1` + `CurrentRoundDataBinding/v1` 明确选择、hash 验证和授权；N+1 可以只继承旧数据、只加入新数据，或两者组合。
- **PR #16 — L6→L7 script contract 修复：**from-memory 的脚本声明继续保留 `name / grounding / branch_id` 等 traceability metadata；L6 gate 和 L7 resolver 共用同一套解析逻辑，不再把整个 object 错当文件名。
- **PR #17 — Meta-RLR maintenance boundary：**增加独立的软件维护层，允许 RLR 自身故障进入 LoopX/Codex 的受限维护流程，但不增加科学 DAG 节点，也不产生第二套科学状态 authority。
- **PR #18 — Meta-RLR scope invariant 修正：**把 Phase 1 的范围测试固定在 PR #17 自己的历史范围，避免以后正常 RLR 功能开发被误判成 Meta-RLR 越界。
- **PR #19–#21 — promotion / governance：**验证后的 stable line 已进入 `main`；`AGENTS.md` 现在明确要求“全局优先、根因优先、单一 authority、禁止补丁堆叠”。这些属于治理变化，不是新的科学运行节点。

---

# 一、角色表：每个人到底负责什么

这是理解 RLR 最重要的一张表。

| 角色 | 正式节点 | 核心职责 |
|---|---|---|
| **Linnaeus（林奈）** | L0、L10c | 一头一尾：L0 负责预检、跨轮恢复和当前轮数据授权；L10c 负责聚合报告、完成人类可读投影并冻结本轮证据。 |
| **Einstein（爱因斯坦）** | L1 | 根据研究问题和已验证文献证据提出**可检验假设**，并提前写明如何证伪。 |
| **Feynman（费曼）** | L2、L9a | 前期攻击“想法”（L2），后期攻击“结果和结论”（L9a）。他的职责就是尽量证明你错了。 |
| **Oppenheimer（奥本海默）** | L3、L6、L10b | 三次正式裁决：L3 选假设，L6 批方法，L10b 做最终 KEEP / REVISE / DOWNGRADE / DROP 决策。 |
| **Fisher（费舍尔）** | L4（内部 L4C） | 根据冻结的方法证据设计分析/实验方案；正式方法 delta 仍是 `L4_fisher`。 |
| **Tukey（图基）** | L5、当前 native v2.1 的 L8 | 执行前审方法和 QC（L5）；执行后审结果、输出文件和可重复性（L8）。 |
| **Turing（图灵）** | L7 | **唯一允许执行代码的角色。**只能运行 L6 批准的脚本，只能使用 `CurrentRoundDataBinding` 授权的数据，只能在受控 workspace 中运行。 |
| **Curie（居里）** | L8.5；同时承担 L1/L4 前的证据检索角色 | 获取、定位和核验真实文献证据；L8.5 用 L7/L8 的实际结果去验证论文证据。 |
| **Darwin（达尔文）** | L9b | 在 L9a 已 finalized 之后，对结果做受证据约束的生物学解释，并明确局限性。 |
| **Jobs（乔布斯）** | L10a | 判断研究价值、论文价值和可以怎样 framing；不能替代最终科学决策。 |

### 一个特别容易混淆的兼容性点

**当前新项目（native v2.1 / `v2.1-catalog-1`）：**

- L8 = **Tukey**
- L9 顺序 = **L9a Feynman → finalized L9a snapshot → L9b Darwin**

**历史 v2.0 项目：**

- L8 = Curie
- L9a / L9b 使用历史并行语义

所以如果你看老文档发现“L8 是 Curie”或者“L9a/L9b 并行”，那是历史 profile，不是当前新项目的默认行为。

---

# 二、每个节点到底做什么

下面这张表以当前 `main` 的 `src/research_loop/topology.py`、L0/L7 gate contract 和 PR #16 之后的正式数据 authority 为准。

| 节点 | 角色 | 它看到什么 | 它真正做什么 | 不能做什么 / 正式效果 |
|---|---|---|---|---|
| **L0** | Linnaeus | candidate frontmatter、权威 `l0_input`、运行环境；continuation 还会看到上一轮 manifest 和明确选择的 inherited refs | 现在的 L0 是 **Pre-flight + State Restore + Current-Round Data Binding**。它检查依赖/运行环境，验证当前数据；如果是 N+1，恢复上一轮冻结证据、逐个验证 path/SHA，再核对本轮选择的 `inherited_inputs`，最后冻结唯一的 `CurrentRoundDataBinding/v1`。 | **不能解释数据、不能执行代码。** blocking dependency、contract、restore、selector 或 hash 任一失败都 fail-closed。 |
| **L1** | Einstein | 研究问题 + L0 + 已验证 pre-research evidence | 提出可检验科学假设。每个假设都必须能操作化，并至少有一个预先声明的 falsification criterion。 | 不设计方法，不执行代码。输出 hypothesis delta。 |
| **L2** | Feynman | L1 假设 + candidate anchor | 对每个 L1 假设做盲审攻击：找混淆因素、逻辑漏洞、替代解释、诊断测试，并按 hypothesis ID 绑定。 | 不改状态，不执行代码；目标不是“帮 L1 完善”，而是尽量攻击。 |
| **L3** | Oppenheimer | L1 + L2 | 看完“假设 + 攻击”后做第一次正式裁决：哪些值得测试，哪些应该淘汰。 | `triage-idea`。可在正式 delta 后运行 shadow ranking，但 ranking 永远只是 advisory。 |
| **L4** | Fisher | L1/L2/L3 + 方法文献证据 | 这是正式方法设计节点，但内部已经拆成可审计的 **L4A → L4B → L4C → L4.5**：先发现文献，再构建方法证据，再由 Fisher 设计方法，最后 deterministic commit。 | 不执行分析代码。正式输出仍是 `L4_fisher` / `METHOD_PROPOSED`。 |
| **L5** | Tukey | L4 方法 + L2 的风险/攻击 | 从 EDA/QC 角度审方法：检查每个策略是否有 QC、stop rule、failure rule，是否真正对应选中的 hypothesis。 | 不改正式状态，不执行代码。 |
| **L6** | Oppenheimer | L4 + L5 | 第二次正式裁决：批准、修改或拒绝分析方案。对于 native/from-memory 路径，脚本必须保留结构化声明，例如 `name / grounding / branch_id`。 | `triage-method`。通过后状态到 `METHOD_APPROVED`。不能为了执行方便把 traceability object 降级成裸字符串。 |
| **L7** | Turing | L6 批准计划 + L0 的当前轮 binding + code-search 结果 | **唯一执行节点。** `execution-gate` 只负责一次性把 `METHOD_APPROVED → NEEDS_EXECUTION`；如果 candidate 已经是 `NEEDS_EXECUTION`，canonical runner 会直接恢复到 workspace preparation，不会强行重复 gate。创建 workspace 前重新验证 binding、contract 和每个输入 hash，只 stage 已授权科学数据和已批准脚本；structured script 通过 canonical `name` 解析。 | 不得运行未批准脚本，不得访问 workspace 外文件，不得用 `input_manifest.md`、`input_alias` 或 `--file` 扩权。数据被篡改时必须在成功 workspace 创建前 fail-closed。 |
| **L8** | Tukey（当前 native v2.1） | L7 输出 + L6 计划 + candidate | 审查 L7 声称产生的每个关键输出，检查可重复性、QC 和 evidence level。它是在“审结果”，不是重新发明一套分析。 | `EXECUTED → AUDITED`。不执行新分析代码。 |
| **L8.5** | Curie | L7 实际结果 + L8 audit + 文献 evidence runtime | 用**实际得到的结果**去找/核验文献；对每个 active hypothesis 做一次支持/矛盾/未解决判断，引用真实 PMID/DOI 和定位 evidence ID。 | `AUDITED → UNDER_REVIEW`。不能伪造引用。 |
| **L9a** | Feynman | L1 + L7 + L8 + L8.5 | 对最终结果做硬证伪：哪些结论真的站得住、哪些已经被数据否掉、还有哪些统计/逻辑缺口。 | 当前 native v2.1 中它必须先 finalized，L9b 才能获得授权 snapshot。 |
| **L9b** | Darwin | L1 + L7 + L8 + L8.5 + **授权后的 finalized L9a snapshot** | 做生物学解释：解释每个 active hypothesis，但只能在已验证证据和 L9a 的约束下解释，并必须写局限性。 | 不执行代码，不做最终 decision；不能绕过 finalized L9a。 |
| **L10a** | Jobs | L8/L8.5/L9a/L9b + candidate framing | 判断科学价值、论文潜力、故事可以讲到什么程度，以及哪里不能 overclaim。 | 只做 value assessment，不改最终状态。 |
| **L10b** | Oppenheimer | L10a + L8 + L8.5 + L9a + L9b | 第三次正式裁决：综合执行审计、文献核验、证伪和生物学解释，给出最终决策。 | 只能是 `KEEP / REVISE / DOWNGRADE / DROP`；理由必须引用前面的审计证据。shadow ranking 仍不能代替正式决策。 |
| **L10c** | Linnaeus | 所有允许的 finalized delta / artifact | 聚合本轮 `FINAL_REPORT.md` 与 `FINAL_REPORT_CN.md`，完成人类可读投影，并冻结本轮证据 manifest。 | 它是**本轮 finalization owner**，不能执行代码，也不能另选一个“新赢家”。 |

---

# 三、L0 现在为什么不只是“依赖检查”

PR #16 之后，L0 已经成为跨轮连续性的正式入口。

```text
上一轮已经冻结的 Round Manifest
        ↓ 逐个验证 path / SHA
L0EvidenceBinding/v1
        ↓ 只选择明确写入 inherited_inputs 的项目
        ┐
        ├── + 本轮 l0_input 中的新数据声明
        ↓
CurrentRoundDataBinding/v1
        ↓
L7 再次验证
        ↓
Turing workspace
```

这三个东西的职责不同：

- `l0_input.yaml`：**声明 authority**——本轮说自己要用什么。
- `L0EvidenceBinding/v1`：**上一轮已验证证据宇宙**——上一轮到底真实存在过什么。
- `CurrentRoundDataBinding/v1`：**本轮执行授权**——上一轮东西很多，但这一次究竟允许哪几个进入当前科学分析。

因此：

- native L0 新写出的 contract 使用 schema 1.1；历史 1.0 仍可读取；
- continuation 可为 inherited-only、new-only、inherited + new；
- inherited file 必须精确匹配上一轮已验证的 path + SHA-256；
- 只能继承 prior `source / intermediate / result` 作为科学数据；
- prior `literature / audit / receipt` 不能偷偷变成分析输入；
- 当前本地文件也必须 hash-bound；
- remote / non-file declaration 可以记录，但在 materialize 成已验证本地文件之前不能给 L7 执行；
- `input_manifest.md`、`input_alias`、`--file` 都不能扩大 machine authority；
- L0 之后有人改了文件，L7 在建 workspace 前会重新 hash 验证并拒绝。

这条链已经经过真实 **Round N → N+1 → L7** acceptance：继承旧 intermediate + 加入新数据、未选择的上一轮 result 不进入 workspace、真实脚本同时读取两份授权输入、tamper 后 fail-closed、恢复后 clean rerun PASS。

---

# 四、L4 内部到底发生什么

L4 在正式 DAG 中仍然只有一个节点，正式存储 key 仍是 `L4_fisher`。

但内部已经分成四个职责清楚的阶段：

```text
L3 selected hypotheses
        ↓
L4A  Literature Discovery
        ↓  L4ADiscoveryManifest/v1
L4B  Evidence Construction
        ↓  Methods / source payload / verified anchors
L4C  Fisher Method Design
        ↓  L4_fisher delta
L4.5 Deterministic Commit
        ↓
L5 Tukey
```

- **L4A：发现。**只负责 query planning、metadata discovery、identifier-first 去重、相关性选择、全文可用性记录。它**不能生成 Methods anchor**。
- **L4B：证据构建。**消费已经冻结的 L4A corpus，调用既有 Academic Research / RLR evidence stack 获取全文、保留 source payload、提取 Methods、核验 anchor、构建 method candidate。
- **L4C：Fisher 真正设计方法。**这是 cognitive method design。
- **L4.5：deterministic commit。**重新验证 L4A manifest、L4B evidence 和 L4C delta hash 后才提交正式方法 projection。

所以 L4A/L4B/L4C/L4.5 是**L4 内部阶段，不是四个新的 DAG 节点**。

---

# 五、文献证据怎么进入 RLR

L1、L4、L8.5 前都需要真实、可定位、可审计的 Academic Research evidence。

| 阶段 | 文献证据用途 |
|---|---|
| L1 前 | 为提出假设提供 Results / Discussion / Conclusion 证据 |
| L4 内 | 冻结 metadata corpus，并获得 primary-study Methods / review evidence |
| L8.5 | 用 L7/L8 的真实结果去做论文支持/矛盾核验 |

RLR 不以“AI 写了一段文献综述”作为证据成功条件。evidence pack 会绑定 runtime receipt、source metadata、可获得的原始 payload、定位摘录和 hash。

架构上坚持 **reuse-first adapter boundary**：成熟检索器/解析器可以接入，但必须作为明确 adapter，而不能变成第二套 evidence authority。Literature Search MCP、Zotero、GROBID、Docling、PaperQA2 等只有在存在真实 consumer 时才应该进入正式依赖关系。

---

# 六、L0 依赖：blocking 和 readiness-only 要分开

当前 L0 不再把所有“未来可能会用到”的服务都当成 blocking dependency。

### 当前 blocking framework checks

对应现在真实存在的 consumer，包括：

- core Python / package / filesystem；
- Academic Research runtime；
- 已激活 Hypothesis Ledger；
- Evidence Store / 项目证据；
- Obsidian projection 所需条件。

### 当前 readiness-only

- **PubMed MCP**
- **Zotero**

它们目前只是 readiness probe；在 planned consumer 真正接上之前，WARN 不等于 L0 blocking failure。

Provider/main-agent readiness 由 runner 在真正知道 active provider 配置时检查；L7 workspace/runtime readiness 继续留在 L7 execution gate。

---

# 七、隔离与 authority

## Path B：认知层隔离

认知角色只收到 controller 根据 DAG 构造出来的 allowed context。它们不能自己遍历项目目录，也不能直接去读上一轮所有文件。

## Path A：Turing 执行隔离

Turing 得到一个受控 workspace，里面只有：

- L6 已批准的脚本；
- DAG 允许的 support artifacts；
- `CurrentRoundDataBinding` 明确授权并再次验证过的本地科学数据。

## 当前几种 authority 不要混淆

| Authority / artifact | 负责什么 |
|---|---|
| **Hypothesis Ledger** | 正式假设生命周期、finalized emission、跨轮 hypothesis state |
| **candidate/frontmatter + delta** | 当前轮各节点的结构化科学状态投影 |
| **RLRRoundEvidenceManifest/v1** | 一轮完成后冻结的物理证据清单 |
| **L0EvidenceBinding/v1** | N+1 对上一轮证据进行完整验证后的可见集合 |
| **CurrentRoundDataBinding/v1** | 当前轮真正允许给 L7 使用的科学数据 |
| **loop memory** | 语义上的下一轮连续性；引用已冻结 manifest，不重新造一份物理证据清单 |

---

# 八、Meta-RLR：在科学 DAG 外面修 RLR 自己

PR #17 新增：

`src/rlr_maintenance/`

它是**软件维护平面**，不是 L11，也不是一个新的 persona。

```text
RLR / CI / acceptance 出现软件故障
        ↓
observer 规范化成 RLRMaintenanceEvent/v1
        ↓
LoopX 维护 goal / todo / evidence / replan
        ↓
Codex 执行受限 repair
        ↓
RLR 自己的 tests / contracts / CI / real acceptance
        ↓
repair 被验证，或者拒绝 repair
```

边界非常重要：

- `research_loop` 永远是科学状态和 contract authority；
- `rlr_maintenance` 可以观察和验证 RLR，但 RLR core 不能反过来依赖 LoopX；
- LoopX 只拥有 maintenance 状态，不拥有 hypothesis、candidate、data binding 或 scientific decision；
- Codex 是 repair worker，不是科学 persona；
- 修复是否成立，最终看 RLR-native tests、contracts、CI 和真实 acceptance；
- **Windows native 是当前 RLR / Meta-RLR repair qualification 的权威运行环境**；如果错误只在 WSL/Linux 出现，它首先是 compatibility/environment evidence，不能仅凭这一点直接改 RLR production code。

PR #18 只是修正这个维护层的历史 scope test，没有改变 production runtime。

---

# 九、Architecture-first：以后改代码先看全局

`AGENTS.md` 现在明确要求所有非平凡修改在动代码前先回答：

1. 为什么必须改？真正被破坏的 invariant / root cause 是什么？
2. 这个责任原本属于哪个 canonical owner？
3. 会不会破坏当前 authority boundary？
4. 有没有更统一、更根本的方案，而不是加一个 workaround？
5. 会不会出现第二套 source of truth、第二 validator、隐藏 fallback 或 compatibility patch？
6. scope 是否最小而完整？

如果局部修复会保留互相矛盾的 authority、累积 compatibility shim 或 patch stack，应先重新设计，而不是继续补。

这是一条**仓库开发治理规则**，不是 RLR 科学 DAG 的新节点。

---

# 十、常用命令

| 命令 | 作用 |
|---|---|
| `demo` | 创建最小 demo |
| `new-project` | 创建 native 项目并绑定 compatibility profile / hypothesis store |
| `new-candidate` | 创建研究 candidate |
| `normalize-l0-input` | 把显式请求/数据声明规范化成严格 L0 contract |
| `preflight` | 运行 L0 pre-flight/readiness |
| `check-deps` | 单独输出依赖/ready 状态 |
| `next-step` | 获取下一个 DAG dispatch packet |
| `deep-research-run` | 执行配置好的 Academic Research 并保存 evidence pack |
| `audit-literature-evidence` / `literature-report` | 证据审计 / 定位证据报告 |
| `assemble-context` | 为一个认知节点生成 Path-B 隔离上下文 |
| `emit-delta` | 校验并持久化节点 delta |
| `triage-idea` | L3 假设裁决 |
| `triage-method` | L6 方法裁决 |
| `execution-gate` | 一次性 `METHOD_APPROVED → NEEDS_EXECUTION` 授权 |
| `prepare-turing-workspace` | 重新验证当前数据 authority 并创建 L7 workspace |
| `decision` | 执行允许的正式状态转换 |
| `aggregate-report` | L10c 聚合最终报告 |
| `obsidian-sync` | Obsidian 人类可读投影 |
| `ranking-shadow` / `ranking-benchmark` / `ranking-report` | advisory ranking；永远不是正式 decision authority |
| `list` / `show` | 查看 candidate |

Canonical runner：

```bash
python run_loop.py run PROJECT CAND
```

`research_loop_v04.py` 继续作为历史 CLI/import compatibility shim；新代码应直接使用 `research_loop.cli`、`research_loop.engine` 或 `research_loop.api`。

---

# 十一、安装与最小检查

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt   # 可选测试依赖

python research_loop_v04.py demo
python research_loop_v04.py --help
python run_loop.py --help
```

真实研究运行必须满足当前 L0 blocking contract 和后续各阶段 gate；readiness-only WARN 会被记录，但不会被静默升级成 blocking failure。

---

# 十二、当前文件结构

```text
research_loop/
├── AGENTS.md                         # repository architecture/change discipline
├── research_loop_v04.py              # 历史 CLI/import compatibility shim
├── run_loop.py                       # 根 runner 入口
├── src/run_loop.py                   # canonical multi-round runner + StopPolicy
├── src/research_loop/
│   ├── cli.py                        # CLI dispatch
│   ├── engine.py                     # 编排操作
│   ├── commands/                     # 各命令 family
│   ├── topology.py                   # DAG / persona / visibility executable truth
│   ├── compatibility.py              # immutable compatibility profiles
│   ├── context.py                    # Path-B context assembly
│   ├── gates.py                      # L0/L4/L6/L7/L10 等 gate
│   ├── delta.py                      # delta schema + shared L6 script projection
│   ├── l0_contract.py                # L0 contract
│   ├── l0_intake.py                  # 请求/数据 normalizer
│   ├── l0_state.py                   # previous-round restore
│   ├── l0_data.py                    # CurrentRoundDataBinding/v1
│   ├── deep_research.py              # Academic Research evidence packs
│   ├── ranking.py                    # advisory shadow ranking
│   └── providers/                    # provider adapters
├── src/rlr_maintenance/              # Meta-RLR maintenance boundary，科学 DAG 之外
│   ├── contracts.py
│   ├── observer.py
│   ├── profiles.py
│   ├── verification.py
│   └── loopx_cli.py
├── docs/DAG_TOPOLOGY.md              # DAG 详细说明
├── docs/MAIN_AGENT_RUN.md            # 主 agent 执行协议
├── docs/MAIN_AGENT_PROMPT.md         # 主 agent 启动提示
├── docs/RUNNER.md                    # runner / StopPolicy
└── templates/                        # layer / persona / project templates
```

真实研究项目、pilot workspace、数据库 WAL、外部 MCP 解压源码和历史运行文件不是 RLR source code，不能因为“存在于本地”就自动进入仓库。

---

# 十三、必须保持不变的硬规则

- L0 遇到 blocking dependency、非法 current input、prior-round restore 失败、inherited selector 错误或 bound-file hash mismatch 时必须 fail-closed。
- `l0_input.yaml` 是本轮输入声明 authority；`CurrentRoundDataBinding/v1` 是本轮 L7 科学数据 execution authority。
- `input_manifest.md`、`input_alias`、`--file` 都不能扩大 scientific data authority。
- 只有 L7 Turing 能执行代码；只能运行批准脚本；只能在 prepared workspace 中运行。
- 当前 native v2.1：L8 = Tukey；L9 = **L9a finalized → authorized snapshot → L9b**。
- Hypothesis Ledger 仍是正式 hypothesis lifecycle authority。
- L10c 负责冻结本轮 physical evidence；loop memory 只引用冻结结果，不能重新发明一份 evidence manifest。
- Meta-RLR 永远位于科学 DAG 之外，不能拥有 scientific state。
- 开发修改必须修 canonical owner / root cause，不能靠复制 authority、兼容 patch 或隐藏 fallback 堆起来。

更详细的 executable-node 说明见：[DAG_TOPOLOGY.md](DAG_TOPOLOGY.md)。
