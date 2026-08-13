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

这张表只回答一件事：**这个角色在研究流程里是干什么的。**

先不讲程序名词，也不讲文件格式。

| 角色 | 出现在哪些步骤 | 说人话：他到底负责什么 |
|---|---|---|
| **Linnaeus（林奈）** | L0、L10c | **负责开门和收尾。**研究开始前，他检查这一轮能不能开工、数据是不是完整可靠；研究结束后，他把整轮结果整理成最终报告并封存记录。 |
| **Einstein（爱因斯坦）** | L1 | **负责提出假设。**他根据研究问题和已有文献提出几个可以真正用数据检验的解释，而且必须提前说清楚：出现什么结果就说明这个假设可能是错的。 |
| **Feynman（费曼）** | L2、L9a | **专门负责找茬。**L2 时挑假设的毛病；结果出来以后，L9a 再挑结果和结论的毛病。目标不是帮你把故事讲漂亮，而是尽量找出哪里站不住。 |
| **Oppenheimer（奥本海默）** | L3、L6、L10b | **负责三次拍板。**第一次决定哪些假设值得继续做；第二次决定方法能不能执行；最后一次决定整轮研究应该保留、修改、降低结论强度，还是放弃。 |
| **Fisher（费舍尔）** | L4 | **负责想“到底怎么做”。**也就是根据前面的假设和方法文献，设计实验方案、统计分析和需要运行的脚本。 |
| **Tukey（图基）** | L5、L8 | **负责前后两次质检。**执行前检查方法有没有明显问题、质控够不够；执行后再检查结果文件、分析过程和结果是否可信。 |
| **Turing（图灵）** | L7 | **负责真正跑代码。**他是整个 RLR 里唯一允许执行分析代码的角色。前面批准了什么，他就执行什么；没有批准的代码和数据不能偷偷使用。 |
| **Curie（居里）** | L8.5；另外也帮助 L1/L4 准备文献证据 | **负责查文献证据。**前面需要设计假设和方法时，她帮忙找到真正的论文证据；结果出来以后，她再去查已有研究到底支持、反对，还是没有回答我们的结果。 |
| **Darwin（达尔文）** | L9b | **负责解释生物学意义。**但他不能先自由发挥故事，必须等费曼先把结果认真挑过一遍毛病，再根据剩下站得住的结果做解释。 |
| **Jobs（乔布斯）** | L10a | **负责判断“这项研究值不值得讲”。**他看科学意义、论文潜力和故事应该讲到什么程度，但不能把弱结果包装成强结论，也不能替代最终科学裁决。 |

### 角色核对结果

当前新项目使用的 **15 个正式节点都有明确角色**，没有需要留空的正式节点。

有一个地方容易混淆：L4 内部还分成 L4A、L4B、L4C、L4.5。它们是 **L4 里面的工作步骤，不是四个新的正式节点**：

- L4A：找方法相关文献；**没有独立 persona**。
- L4B：把真正可用的方法证据整理出来；**没有独立 persona**。
- L4C：由 **Fisher（费舍尔）**真正设计方法。
- L4.5：系统检查前面三步是否一致，然后保存结果；**没有独立 persona**。

所以以后如果单独列 L4A、L4B、L4.5，角色栏应该留空，而不是硬给它们安一个人物名字。

### 旧版本和当前版本有一个差别

当前新项目（native v2.1 / `v2.1-catalog-1`）里：

- **L8 是 Tukey（图基）**；
- **L9a 先做，L9b 后做**。也就是先让费曼挑毛病，再让达尔文解释。

历史 v2.0 的 L8 和 L9 顺序不一样。以后看老文档时，如果发现 L8 写成 Curie，或者 L9a/L9b 写成并行，不代表当前版本也是这样。

---

# 二、每个节点到底做什么

这一张表只回答四个问题：**现在走到哪一步、谁来做、这一部到底干什么、做完以后得到什么。**

程序里的状态名、文件名和 contract 名先不放进主表；需要查实现细节时，再看第三节以后。

| 节点 | 角色 | 说人话：这一部到底干什么 | 做完以后得到什么 |
|---|---|---|---|
| **L0** | Linnaeus（林奈） | **开工前检查。**先确认程序环境能不能工作、这一轮准备使用的数据在不在、有没有被改坏。如果这是上一轮研究的继续，还要确认上一轮留下来的数据确实是原来的那一份，并明确这一轮到底允许继续使用哪些旧数据。这里不分析数据，只做检查和放行。 | 得到一份明确的“**这一轮允许使用哪些数据**”的记录。全部检查通过后，研究才进入 L1。 |
| **L1** | Einstein（爱因斯坦） | **提出假设。**根据研究问题和已有文献，提出几个可能的科学解释。每个假设都必须能用数据检验，而且要提前写清楚：什么样的结果会让这个假设站不住。 | 得到一组待检验的科学假设，交给 L2 挑毛病。 |
| **L2** | Feynman（费曼） | **第一次找茬。**逐个攻击 L1 的假设：有没有混淆因素？有没有更简单的替代解释？逻辑有没有漏洞？需要什么额外检查才能证明它不是假象？ | 得到每个假设的风险和反对意见，交给 L3 判断哪些还值得继续。 |
| **L3** | Oppenheimer（奥本海默） | **第一次拍板：选假设。**把 L1 的假设和 L2 的批评放在一起看，决定哪些假设值得花时间和算力继续验证，哪些现在就应该淘汰。 | 得到正式进入下一阶段的假设名单。 |
| **L4** | Fisher（费舍尔） | **设计怎么做。**先找和方法有关的论文，把真正有用的方法证据整理出来；然后 Fisher 根据这些证据，设计实验或分析方案，并说明需要跑哪些脚本。 | 得到一套“准备怎么验证这些假设”的方法方案，交给 L5 审查。 |
| **L5** | Tukey（图基） | **执行前质检。**专门检查 L4 的方法靠不靠谱：有没有缺少必要的质控？什么情况下应该停止？什么结果说明分析失败？方法是不是实际上没有回答原来的假设？ | 得到一份方法问题清单和质控要求，交给 L6 决定方法能不能用。 |
| **L6** | Oppenheimer（奥本海默） | **第二次拍板：批方法。**综合 L4 的方案和 L5 的批评，决定这套方法是可以直接执行、需要修改，还是不能执行。 | 得到最终允许执行的分析方案和脚本清单。只有通过这一关，才能进入 L7。 |
| **L7** | Turing（图灵） | **真正跑代码。**这是整个流程里唯一真正执行分析代码的一步。运行前还会再检查一次数据有没有被改过；然后只把前面批准的数据和脚本放进工作区执行。 | 得到真实的分析结果、输出文件和运行记录。 |
| **L8** | Tukey（图基） | **执行后质检。**检查 L7 说自己生成的结果到底是不是真的存在，关键输出是否完整，分析是否按批准的方法完成，质控有没有通过，结果能不能被复现。这里不是再发明一套新分析。 | 得到一份“这些结果到底有多可信”的审查结果。 |
| **L8.5** | Curie（居里） | **拿实际结果去查文献。**不是泛泛搜论文，而是根据 L7/L8 已经得到的真实结果，去看已有研究是支持它、和它矛盾，还是目前没有足够证据判断。 | 得到“我们的结果和已有文献是什么关系”的核验结果。 |
| **L9a** | Feynman（费曼） | **第二次找茬，而且这次专门攻击结论。**检查统计和逻辑是否真的支持当前说法：哪些结论还站得住，哪些已经被数据否掉，哪些其实证据还不够。 | 得到一份“哪些结论能留、哪些不能留、哪些还不确定”的清单。完成后才轮到 L9b 做解释。 |
| **L9b** | Darwin（达尔文） | **解释生物学意义。**在已经看过 L9a 批评的前提下，解释剩下结果可能意味着什么，同时必须把局限性说清楚。 | 得到受证据约束的生物学解释，而不是一个脱离数据自由发挥的故事。 |
| **L10a** | Jobs（乔布斯） | **判断这项工作值不值得讲、应该怎么讲。**看科学意义、论文潜力、结果能支持多强的故事，以及哪里必须克制，不能夸大。 | 得到研究价值和论文表达方向的建议。 |
| **L10b** | Oppenheimer（奥本海默） | **最后一次拍板。**把结果质检、文献核验、费曼的证伪、达尔文的解释和 Jobs 的价值判断全部放在一起，决定这一轮研究最终怎么处理。 | 四种结果之一：**KEEP**（保留）、**REVISE**（修改后再来）、**DOWNGRADE**（降低结论强度）或 **DROP**（放弃）。 |
| **L10c** | Linnaeus（林奈） | **收尾。**把这一轮前面所有步骤的最终内容按顺序整理成报告，把证据和结果记录固定下来，保证下一轮以后还能知道这一轮到底做过什么。 | 得到本轮最终报告，并正式结束这一轮研究。 |

如果只想理解 RLR 的科学流程，看到这里已经够了。后面的章节主要解释程序上**怎样保证这些角色不会越权、数据不会被偷偷换掉、文献证据可以追溯**。

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