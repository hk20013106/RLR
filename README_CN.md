# Research Loop Room (RLR) — 研究循环室

[English](./README.md) | **中文**

---

## 这是什么

RLR 是一个**科学研究的自动化审查框架**。它把一个研究问题（"高心率物种是否共享心房/心室共表达模块？"）变成一条**15 步流水线**，每一步由一个独立角色（persona）执行，角色之间通过结构化数据传递信息，而不是共享上下文。

核心设计问题它要解决的是：**当 AI 同时扮演"提出假设的人"和"批判假设的人"时，批判是假的**——它不会真正攻击自己刚写的东西。RLR 用物理隔离来强制独立性：每个角色只能看到 DAG 拓扑允许它看的输入，看不到其他任何东西。

一句话：**用多角色对抗 + 文献锚定 + 执行门禁，把"AI 做研究"从自由发挥变成有约束的审查流程。**

**当前版本：V0.7**（canonical gated runtime）

---

## 版本历史

### V0.7 — 当前（canonical gated runtime）
- **L0 严格输入契约**：`normalize-l0-input` 将请求文件和显式数据位置规范化为可验证、可审计的 L0 contract；不从自然语言猜测路径、ID、决策或结论。
- **假说排序可靠性层（shadow mode）**：对显式候选集合执行 A/B 与 B/A 的公平 pairwise 判断；顺序翻转标记为 `UNCERTAIN`，并将排序、checkpoint、evidence event、正式决策分歧和失败审计隔离写入 `08_Audit/ranking/`。它绝不改变正式 gate、候选选择或 decision。

### v0.4.5 — 已被 V0.7 取代（2026-06-26）
- **新增 L8.5 文献验证节点**：居里 的第二实例。L7/L8 出结果后，L8.5 基于**实际结果**检索 PubMed/EuropePMC，验证结论是否与已发表文献一致。同时引入可增长的文献数据库（`manage_literature_db.py`），跨轮复用。
- **新增 L0 依赖门禁**（硬停止）：`preflight` / `check-deps` 在 L0 检查所有必需依赖（PyYAML、Academic Research skill、Zotero、Obsidian vault），任一缺失就**退出码非零，循环停止**——不允许跳过。
- **修复**：`sync_to_obsidian` 的 UTF-8 编码问题；`assemble-context` 在 Windows 控制台打印非 GBK 字符时崩溃的问题。

### v0.4.x — 超级版本（保留参考）
- **新增三个预研步骤**（不改 DAG 节点数）：L1 前做深度文献检索，L4 前做方法论文综述，L7 前做代码库搜索。预研结果嵌入对应节点的 `assemble-context`，并记录在 context manifest 中。
- **修复**：预研结果之前写了但没嵌入上下文（功能是死的）；预研查询之前硬编码了一个项目的查询，现在改为基于 candidate 自己的 question/claim 动态生成。`sync_to_obsidian` 在无 `$OBSIDIAN_VAULT` 时不再创建垃圾目录（改为报错退出）。
- **文件**：`research_loop_v04.py`

### v0.3 — 超级版本（保留参考）
- **做了什么**：把每个角色变成**隔离的 subagent**，跑一个 **14 节点 DAG**（L0–L10c；L9a/L9b 并行）。
- **修复了 v0.2 的问题**：单上下文污染。每个节点现在只能看到 DAG 允许的输入（路径 B = 上下文不可见）；执行隔离到 workspace（路径 A）。自由格式笔记被**结构化 delta JSON** 取代，带递归 schema 验证。
- **新增**：`next-step` / `assemble-context` / `emit-delta` / `prepare-turing-workspace` 控制器命令；审计追踪（context manifest + run receipt + 哈希）；循环运行器（`run_loop.py` + `orchestrator.py`），支持 main-agent / headless / manual 三种模式，混合 StopPolicy，子 candidate 轮次；中英文 FINAL_REPORT；Obsidian 人类可读同步。
- **文件**：`research_loop_v03.py`、[DAG_TOPOLOGY.md](DAG_TOPOLOGY.md)

### v0.2 — 废弃（保留，仍可运行）
- **做了什么**：重构为**门控的 10 人格委员会**（林奈 … 乔布斯），单一共享上下文，带决策日志和 Obsidian 同步。
- **修复了 v0.1 的问题**：补上了缺失的**门禁**——L0 技能/预检门禁、candidate 裁决、方法裁决、执行门禁（只有 图灵 跑代码，且只在门禁通过后）。7→10 人格，9→15 状态。
- **仍有的问题**：10 个人格共享**一个上下文窗口**，推理会交叉污染（比如假设的提出者看到了对自己假设的批判）。
- **文件**：`research_loop_v02.py`（保留不动）

### v0.1 — 已删除
- **做了什么**：7 agent 的**线性**循环（Idea → Value → Evidence → Falsification → Biology → Decision → Execution），9 个状态，所有 agent 共享一个上下文。
- **为什么删除**：没有技能门禁、没有方法裁决、没有执行安全、没有上下文隔离。架构不合理，已删除（未保留）。

---

## 架构（V0.7）

### DAG 流水线（15 个节点）

一个研究问题从 L0 走到 L10c，经过 15 个节点。每个节点由一个角色执行，只看该看的东西。

```
L0  林奈         预检 + 依赖门禁（缺依赖则停止）
       │
L1  爱因斯坦     提出假设（前面先做深度文献检索）
       │
L2  费曼         盲审攻击 L1 的假设
       │
L3  奥本海默     裁决：选出可测试的假设
       │
L4  费舍尔       设计方法（前面先做方法论文综述）
       │
L5  图基         审查方法设计
       │
L6  奥本海默     批准分析方案
       │
L7  图灵         执行脚本（前面先做代码搜索）
       │
L8  居里         审计结果，验证可重复性
       │
L8.5 居里        文献验证：拿实际结果去查 PubMed
       │
L9a 费曼 ╮       并行（互相不可见）
L9b 达尔文 ╰──→  证伪 / 生物学解读
       │
L10a 乔布斯      价值评估，规划论文方向
       │
L10b 奥本海默    终审：KEEP / REVISE / DOWNGRADE / DROP
       │
L10c 林奈        聚合所有 delta，生成最终报告
```

### L0 依赖契约（V0.7）

L0 当前有 **4 项框架级必需依赖**。这是 fail-closed 门禁：任一项缺失，循环在 L0 停止，不会进入 L1。

| 依赖 | 检测/声明方式 | 用途 |
|------|---------------|------|
| PyYAML | Python import `yaml` | contract、frontmatter 和文献数据库 I/O |
| Academic Research skill | `RLR_SKILL_ACADEMIC_RESEARCH=1` | L1/L4 预研和 L8.5 文献验证 |
| Zotero connector | `127.0.0.1:23119` 或 `RLR_ZOTERO` | 文献管理和引用来源 |
| Obsidian vault | 有效 `$OBSIDIAN_VAULT` 路径或 `RLR_OBSIDIAN` | 回合结束的人类可读同步 |

项目还可以在 `00_Preflight/dependencies.md` 中用 `- python:`、
`- command:` 或 `- env:` 增加依赖；这些是附加项，不会替代上述 4 项。

### 隔离机制：为什么需要，怎么实现

**问题**：如果 AI 同时扮演假设提出者（爱因斯坦）和假设批判者（费曼），它会倾向于不攻击自己刚写的东西。这不是 AI 的"性格"问题，而是**信息泄露**——批判者看到了提出者的推理过程，所以它的"批判"本质上是自我辩护的延伸。

**解决方法**：物理隔离。每个角色只能看到 DAG 允许它看的输入，看不到其他任何东西。代码里通过两种路径实现：

**路径 B — 认知层隔离（所有角色，除 图灵）**

控制器调用 `assemble-context`，把该节点允许看到的 delta 内容拼成一段纯文本，嵌入 `spawn_agent` 的 message。角色只看到这段文本，没有文件系统访问权限，看不到其他节点的 delta。

```
爱因斯坦 只看到：candidate frontmatter + L0 delta
费曼     只看到：candidate frontmatter + L1 delta（爱因斯坦的假设）
                    —— 他不知道 爱因斯坦 的推理过程，只看到结论
奥本海默 看到：L1 + L2（假设 + 攻击），做裁决
```

**路径 A — 执行层隔离（只有 图灵）**

图灵 要跑代码，不能纯上下文隔离。控制器调用 `prepare-turing-workspace`，用 `shutil.copy2` 把白名单文件复制到同盘临时目录，图灵 在这个 workspace 里执行 R/Python 脚本。结果被收集打包成 L7 delta JSON。

**我们不假装 `spawn_agent` 是操作系统沙箱**。路径 B 的隔离靠的是"信息不可见"——角色的上下文里根本没有不该看的内容，不是靠文件系统权限。真正的文件系统沙箱只有 图灵 的 workspace（路径 A）。

### 预研步骤（L1 / L4 / L7 之前）

| 在哪个节点之前 | 步骤 | 做什么 |
|----------------|------|--------|
| L1 | 深度文献检索 | 基于 candidate 的问题检索 PubMed/EuropePMC，让假设有文献依据 |
| L4 | 方法综述 | 搜方法论文，看别人怎么跑类似分析 |
| L7 | 代码搜索 | 搜 GitHub/Bioconductor/CRAN，复用已有 pipeline |

预研不改 DAG 节点数。结果写入 `02_Agent_Notes/_pre_research/<node>_research.md`，被 `assemble-context` 嵌入对应节点的上下文。

### L8.5 文献验证节点

L7/L8 出结果后，L8.5（居里 的第二实例）基于**实际结果的关键词**去检索 PubMed/EuropePMC，验证结论是否与已发表文献一致。找到的论文加入可增长的文献数据库（`09_Literature_Database/`），跨轮复用，通过 Obsidian wikilink 引用。

### L0 依赖门禁（硬停止）

`preflight` / `check-deps` 检查所有必需依赖，任一缺失就退出码非零，**循环停止**。必需依赖：PyYAML、Academic Research skill、Zotero（端口 127.0.0.1:23119）、Obsidian vault（`$OBSIDIAN_VAULT`）。Python 无法内省的东西（Claude skill、GUI app）通过 `RLR_*` 环境变量 attestation。

---

## 角色表

| 节点 | 角色 | 职责 | 隔离方式 |
|------|------|------|----------|
| L0 | 林奈 | 预检、扫描技能、验证输入数据 | 路径 B |
| L1 | 爱因斯坦 | 提出科学假设 | 路径 B |
| L2 | 费曼 | 盲审攻击 L1 假设，找混淆因素 | 路径 B |
| L3 | 奥本海默 | 裁决假设，选出可测试的 | 路径 B |
| L4 | 费舍尔 | 设计实验/分析策略 | 路径 B |
| L5 | 图基 | 从 EDA/QC 角度审查方法 | 路径 B |
| L6 | 奥本海默 | 批准或驳回分析方案 | 路径 B |
| L7 | 图灵 | 在受控 workspace 中执行脚本 | **路径 A** |
| L8 | 居里 | 审计结果，验证可重复性 | 路径 B |
| L8.5 | 居里 | 文献验证，增长文献数据库 | 路径 B |
| L9a | 费曼 | 硬证伪（统计/逻辑完备性） | 路径 B（与 L9b 并行，互不可见） |
| L9b | 达尔文 | 生物学解读 | 路径 B（与 L9a 并行，互不可见） |
| L10a | 乔布斯 | 价值评估，规划论文方向 | 路径 B |
| L10b | 奥本海默 | 终审：KEEP / REVISE / DOWNGRADE / DROP | 路径 B |
| L10c | 林奈 | 聚合所有 delta，生成最终报告 | 读取所有 delta |

### V0.7 每个节点到底做什么

| 节点 | 读取 | 产出 | 正式效果 |
|------|------|------|----------|
| L0 林奈 | candidate frontmatter + 严格 L0 contract | 输入验证、技能计划、依赖/预检审计 | 缺依赖或输入未验证则停止；通过后进入 `IDEA_PROPOSED` |
| L1 爱因斯坦 | frontmatter + L0 | 可测试假设、主假设 | 生成假设 delta |
| L2 费曼 | frontmatter + L1 | 盲审攻击、混淆因素、诊断检验 | 不改状态 |
| L3 奥本海默 | L1 + L2 | 选中/拒绝假设及理由 | `triage-idea`；delta 成功写入后才可触发 shadow ranking |
| L4 费舍尔 | L1/L2/L3 + 方法预研 | 策略、脚本、参数、输出计划 | 提出分析方案 |
| L5 图基 | L4 + L2 | QC 检查点、失败规则、方法攻击 | 不改状态 |
| L6 奥本海默 | L4 + L5 | 分析方案批准/拒绝及修改 | `triage-method`；刻意不接入 ranking hook |
| L7 图灵 | L6 + L0 + 准备好的白名单 workspace | 脚本退出码、输出文件、关键结果 | 唯一允许执行代码的节点；先过 `execution-gate` |
| L8 居里 | L7 + L6 + frontmatter | 证据审计、可重复性检查、证据等级 | 进入 `AUDITED` |
| L8.5 居里 | L7 + L8 + 文献预研 | PubMed/EuropePMC 验证和文献记录 | 进入 review |
| L9a 费曼 | L1 + L7 + L8 + L8.5 | 统计/逻辑证伪 | 与 L9b 并行，不能读取 L9b |
| L9b 达尔文 | L1 + L7 + L8 + L8.5 | 生物学解读和局限 | 与 L9a 并行，不能读取 L9a |
| L10a 乔布斯 | frontmatter + L8/L8.5/L9a/L9b | 价值评估和论文框架 | 不改状态 |
| L10b 奥本海默 | L10a + L8/L8.5/L9a/L9b | 最终决策、证据等级、理由、下一假设 | `KEEP/REVISE/DOWNGRADE/DROP`；delta 成功写入后才可触发 shadow ranking |
| L10c 林奈 | 所有允许读取的 delta | 中英文 FINAL_REPORT 和同步输入 | 聚合报告；不执行代码，也不替 ranking 选胜者 |

ranking 只是 L3/L10b 之后生成的 advisory signal，不参与
`triage-idea`、`triage-method` 或正式 `decision` 转移校验。

### V0.7 运行时分层

1. **兼容/分发层：** `research_loop_v04.py` 保留历史命令和 import 路径；
   `research_loop/cli.py` 将请求分发到 engine。
2. **DAG 契约层：** `topology.py` 定义节点、允许输入、状态和转移；
   `delta.py` 定义结构化输出 schema。
3. **上下文与门禁层：** `context.py` 组装 Path B manifest；`gates.py` 执行
   L0 输入、预研、执行和 traceability 校验。
4. **持久化层：** `paths.py`、`yamlio.py`、`ledger.py` 与 candidate-owned
   delta 文件提供隔离、可哈希的项目 artifact。
5. **执行/provider 层：** `providers/` 选择 main-agent、command、headless
   或 manual；`api.py` 提供进程内 facade；`run_loop.py` 驱动多轮和 StopPolicy。
6. **专用能力层：** `l0_contract.py`/`l0_intake.py` 负责严格 L0 规范化；
   `ranking.py` 负责 advisory ranking artifact，绝不写入正式 decision 状态。

---

## 记忆共享（4 层）

1. **Delta JSON**（主，项目内）：角色间状态传递的唯一方式。
2. **Candidate frontmatter**（只读锚点）：candidate_id、title、question、claim 被剥离后嵌入每个角色上下文。candidate body（状态/历史）不传给 subagent。
3. **文献数据库**（跨轮，项目内）：`09_Literature_Database/`，由 `manage_literature_db.py` 管理，去重，通过 Obsidian wikilink 引用。
4. **EverOS**（跨会话，可选）：持久技术事实。subagent 可在启动时搜索声明的 `everos_read_scopes`。

**不是记忆机制**：没有共享上下文窗口、没有共享变量、认知层没有文件系统访问、不传 candidate body。

---

## 命令

| 命令 | 说明 |
|------|------|
| `demo` | 生成 demo 项目，走完 15 个节点 |
| `new-project` | 创建 V0.7 项目目录 |
| `preflight` | L0 预检 + 依赖门禁 |
| `normalize-l0-input` | 将显式请求和数据位置规范化为严格 L0 contract |
| `check-deps` | 独立依赖检查 |
| `new-candidate` | 创建带拆分 frontmatter 的 candidate |
| `next-step` | 获取下一个 DAG 节点调度包 |
| `pre-research` | 打印 L1/L4/L7 的预研提示 |
| `assemble-context` | 构建节点的隔离上下文 |
| `emit-delta` | 校验并写入 delta JSON |
| `route` | 把 candidate 交给一个角色 |
| `note` | 追加角色笔记 |
| `triage-idea` | L3：假设裁决 |
| `triage-method` | L6：方法裁决 |
| `execution-gate` | 执行门禁 |
| `decision` | 状态变更 |
| `aggregate-report` | L10c：生成 FINAL_REPORT |
| `obsidian-sync` | 同步到 Obsidian vault |
| `ranking-shadow` | 对显式候选运行隔离的 advisory 公平排序 |
| `ranking-benchmark` | 运行免费的 synthetic fair-vs-naive 排序 benchmark |
| `ranking-report` | 输出 shadow ranking artifact 的 JSON 或 Markdown 报告 |
| `list` | 列出 candidate |
| `show` | 查看 candidate 文件 |

---

## 严格 L0 intake 与假说排序 shadow mode

`normalize-l0-input` 只接受显式本地数据路径（或稳定的远程 dataset locator），把请求文件转换为经过验证的 L0 contract。`--dry-run` 不写入任何候选或 artifact；`--run-l0` 只启动 canonical runner 到 L0 为止。

```bash
python research_loop_v04.py normalize-l0-input \
  --project MyProject --input request.md --data data_directory --dry-run
```

Hypothesis Ranking Reliability Layer 仅是 **shadow signal**：它对一组明确给出的候选进行成对比较，每一对都执行 A/B 和 B/A 两次；结果冲突时标记 `UNCERTAIN`，绝不为了完整排名强制判胜。默认使用免费、确定性的 fake judge；真实 provider 必须显式配置。所有产物都隔离在 `08_Audit/ranking/`，不会改变 candidate status、L3/L10b 正式 decision 或任何 gate。

```bash
# 独立运行 L3 或 L10b 的 shadow ranking。
python research_loop_v04.py ranking-shadow MyProject --stage L3 \
  --candidate C001 --candidate C002 --seed 7 --match-budget 10

# 运行免费的 synthetic benchmark，并渲染已保存 artifact。
python research_loop_v04.py ranking-benchmark --gold gold.json --seeds 1,2,3 --match-budget 10
python research_loop_v04.py ranking-report MyProject --run <RUN_ID> --format markdown

# 在 canonical run 中显式开启。只接入 L3/L10b；刻意不接入 L6。
python run_loop.py run MyProject C001 --shadow-ranking \
  --shadow-candidate C002 --shadow-seed 7 --shadow-match-budget 10
```

shadow ranking 的超时、失败或不完整 artifact 都会留下审计记录并 fail-soft；既有 RLR 正式决策链继续运行。

---

## 文件结构

```
research_loop/
├── research_loop_v04.py          # 历史 CLI/import 兼容 shim，不是当前 engine 实现
├── research_loop/
│   ├── cli.py                    # 稳定 CLI 分发入口
│   ├── engine.py                 # 命令处理和编排操作
│   ├── api.py                    # 进程内 EngineAPI facade
│   ├── topology.py               # DAG 节点、转移和可见输入
│   ├── context.py                # Path B 上下文组装与 manifest
│   ├── gates.py                  # L0/L1/L7/L10 门禁和可追溯性校验
│   ├── delta.py                  # delta schema 和 candidate-owned 解析
│   ├── l0_contract.py            # L0 schema、validator、serializer、renderer
│   ├── l0_intake.py              # 规则型请求/数据 normalizer
│   ├── providers/                # main-agent、command、headless、manual provider
│   ├── ranking.py                # shadow judge、Elo、checkpoint、evidence
│   ├── paths.py / yamlio.py      # 安全路径和 YAML/frontmatter I/O
│   ├── ledger.py / presearch.py  # pitfall/evidence ledger 与预研
│   └── errors.py                 # 类型化运行时错误
├── research_loop_v03.py          # 保留参考
├── run_loop.py                   # 循环运行器
├── orchestrator.py               # Provider 抽象
├── manage_literature_db.py       # 文献数据库
├── sync_to_obsidian.py           # Obsidian 同步
├── MAIN_AGENT_RUN.md             # 主 agent 执行协议
├── MAIN_AGENT_PROMPT.md          # 主 agent 启动提示词
├── RUNNER.md                     # 运行模式 + StopPolicy
├── DAG_TOPOLOGY.md               # DAG 依赖表
├── templates/v03_layers/         # 15 个 layer 模板
├── templates/v03_personas/       # 10 个人格模板
└── DemoProject_v03/              # 跟踪的示例项目
```

`research_loop_v04.py` 只是为了兼容历史测试和外部自动化而保留的文件名；
它把调用转发给 `research_loop.cli`，不再承载当前 engine 主体。新代码应直接导入
`research_loop.engine`、`research_loop.cli` 或 `research_loop.api`。

## 环境

- Python 3.13（标准库）+ PyYAML；R 4.6.0（L7 用）；Windows 11 / PowerShell。
- 必需外部依赖（L0 门禁）：Academic Research skill、Zotero、Obsidian vault（`$OBSIDIAN_VAULT`）。
- EverOS：可选，可配置端点。
