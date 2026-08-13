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

这张表只回答一件事：**这个人在研究流程里负责哪一类工作。**

| 角色 | 出现在哪些步骤 | 说人话：他到底负责什么 |
|---|---|---|
| **Linnaeus（林奈）** | L0、L10c | **管开头和结尾。**开始前确认这轮研究能不能开工；结束时把这一轮做过什么、得到什么整理好并保存下来。 |
| **Einstein（爱因斯坦）** | L1 | **想几个可能的答案。**围绕研究问题提出几个科学解释，而且这些解释必须能用数据判断对不对。 |
| **Feynman（费曼）** | L2、L9a | **专门挑毛病。**前面挑假设的毛病，后面挑结果和结论的毛病。他的工作就是尽量找出哪里不成立。 |
| **Oppenheimer（奥本海默）** | L3、L6、L10b | **负责拍板。**决定哪些假设值得继续、哪些方法可以真的去做，以及最后这轮研究应该保留、修改还是放弃。 |
| **Fisher（费舍尔）** | L4 | **负责想具体怎么做。**别人过去怎么研究这个问题？我们应该做什么实验、跑什么分析、用什么步骤去验证假设？ |
| **Tukey（图基）** | L5、L8 | **负责前后两次检查。**做之前检查方法有没有明显漏洞；做完以后检查结果有没有跑错、能不能相信。 |
| **Turing（图灵）** | L7 | **负责真正跑代码。**这是整个 RLR 里唯一真正执行分析代码的人。前面批准什么，他就做什么。 |
| **Curie（居里）** | L8.5；另外也帮助 L1/L4 找文献 | **负责查论文。**前面帮忙找提出假设和设计方法需要的论文；结果出来后，再查别人有没有得到过类似或相反的结果。 |
| **Darwin（达尔文）** | L9b | **负责解释生物学意义。**但要先等费曼把结果挑完毛病，再解释剩下真正站得住的部分。 |
| **Jobs（乔布斯）** | L10a | **负责判断这项研究值不值得讲、应该怎么讲。**主要看科学意义和论文价值，但不能把弱结果包装成强结论。 |

### 角色核对结果

当前新项目使用的 **15 个正式节点都有明确角色**，没有需要留空的正式节点。

L4 里面还有 L4A、L4B、L4C、L4.5 四个内部步骤，但它们不是四个新的正式节点：

- L4A：找方法相关文献；**没有独立角色**。
- L4B：把真正有用的方法信息整理出来；**没有独立角色**。
- L4C：由 **Fisher（费舍尔）**真正设计方法。
- L4.5：系统检查前面几步有没有对得上，然后保存结果；**没有独立角色**。

所以以后如果把 L4A、L4B、L4.5 单独列出来，角色栏应该留空，不要硬给它们安一个人物名字。

### 旧版本和当前版本有一个差别

当前新项目（native v2.1 / `v2.1-catalog-1`）里：

- **L8 是 Tukey（图基）**；
- **L9a 先做，L9b 后做**。也就是先让费曼挑毛病，再让达尔文解释。

历史 v2.0 的 L8 和 L9 顺序不一样。以后看老文档时，如果发现 L8 写成 Curie，或者 L9a/L9b 写成并行，不代表当前版本也是这样。

---

# 二、每个节点到底做什么

下面这张表只讲研究流程本身。**不讲程序内部名词，不讲文件格式，也不讲代码实现。**

可以把它理解成一条研究流水线：前一步把东西交给下一步，下一步继续处理。

| 节点 | 谁来做 | 这一步到底在干什么 | 做完以后交给下一步什么 |
|---|---|---|---|
| **L0** | Linnaeus（林奈） | **先看看能不能开工。**数据在不在？是不是原来的那份？程序能不能正常工作？如果是接着上一轮继续做，还要确认这一轮准备继续使用哪些旧数据。这里不分析结果，只负责把开工前的东西检查清楚。 | 一份已经确认好的“这轮研究要用什么”的清单，然后进入 L1。 |
| **L1** | Einstein（爱因斯坦） | **围绕研究问题想几个可能的答案。**比如“可能是因为 A”“也可能是因为 B”。但不能只是猜，每个答案都要能用后面的数据判断对不对。 | 一组准备接受检验的假设，交给 L2。 |
| **L2** | Feynman（费曼） | **专门反驳 L1。**逐个问：这个假设是不是还有别的解释？是不是漏掉了重要因素？即使得到预期结果，会不会其实也不能证明它？ | 每个假设最可能出问题的地方，交给 L3。 |
| **L3** | Oppenheimer（奥本海默） | **决定哪些假设值得继续做。**把 L1 的想法和 L2 的反对意见放在一起看。太弱、明显站不住的现在就淘汰，值得验证的留下。 | 真正进入下一阶段的假设，交给 L4。 |
| **L4** | Fisher（费舍尔） | **想清楚到底怎么验证这些假设。**先看看别人以前怎么做，然后决定我们这次具体做什么实验、分析哪些数据、采用什么分析步骤。 | 一套具体的研究办法，交给 L5。 |
| **L5** | Tukey（图基） | **在真正开跑前，先找这套办法的问题。**比如：哪里容易出错？哪些检查不能少？出现什么情况说明这次分析不能继续相信？ | 一份“这套方法哪里要小心”的清单，交给 L6。 |
| **L6** | Oppenheimer（奥本海默） | **决定这套办法能不能真的去做。**如果 L5 找到的问题没有解决，就退回去改；如果已经足够可靠，就正式放行。 | 最终确定的分析办法，交给 L7。 |
| **L7** | Turing（图灵） | **真正开始跑数据和代码。**前面决定怎么做，这一步就按那个办法实际执行。不能临时自己换方法，也不能偷偷加入前面没批准的数据。 | 真正跑出来的结果，交给 L8。 |
| **L8** | Tukey（图基） | **检查刚才跑出来的东西有没有问题。**有没有跑错？结果文件齐不齐？是不是按前面说好的办法做的？别人照着同样步骤做，能不能得到同样结果？ | 一份“这些结果到底靠不靠谱”的判断，交给 L8.5。 |
| **L8.5** | Curie（居里） | **把我们的实际结果拿去和已有论文对照。**看看别人以前有没有发现类似现象，有没有相反结果，或者这个问题其实还没人真正回答。 | “我们的结果和已有研究是什么关系”的结论，交给 L9。 |
| **L9a** | Feynman（费曼） | **对最终结论再泼一次冷水。**哪些说法真的有数据支持？哪些只是看起来像？哪些说得太满？还有没有别的解释？ | 一份“哪些结论能留、哪些要删、哪些还不能确定”的清单，交给 L9b。 |
| **L9b** | Darwin（达尔文） | **解释这些结果在生物学上意味着什么。**但只能解释经过 L9a 挑完毛病以后还站得住的部分，不能为了讲故事自己补东西。 | 一套比较可靠的生物学解释，交给 L10。 |
| **L10a** | Jobs（乔布斯） | **判断这项工作值不值得写、最值得讲什么。**哪些发现最重要？论文的重点应该放哪里？我们的结果最多能支持多强的说法？ | 一份关于研究价值和论文重点的建议，交给 L10b。 |
| **L10b** | Oppenheimer（奥本海默） | **做最后决定。**综合前面的结果、质疑、文献和解释，决定这轮研究是可以保留，还是需要修改、降低结论强度，或者干脆放弃。 | 这轮研究的最终决定，交给 L10c。 |
| **L10c** | Linnaeus（林奈） | **收尾。**把这一轮前面所有步骤整理成最终报告，并把重要结果和记录保存好，方便以后继续下一轮。 | 最终报告。这一轮到这里结束。 |

如果只想理解 RLR 的科学流程，看到这里已经够了。后面的章节主要讲程序上怎样保证这些步骤不会乱套。

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