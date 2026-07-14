# Research Loop Room (RLR) — 研究循环室

[English](../README.md) | **中文**

---

## 这是什么

RLR（Research Loop Room）是一个**证据门禁的科学研究审查框架**。它把一个研究问题变成一条**15 步流水线**，每一步由一个独立角色（persona）执行，角色之间通过结构化数据传递信息，而不是共享上下文。RLR 不替研究者做最终判断，而是把假设、批判、方法、执行、审计和最终决策组织成可追溯流程。

核心设计问题它要解决的是：**当 AI 同时扮演"提出假设的人"和"批判假设的人"时，批判是假的**——它不会真正攻击自己刚写的东西。RLR 用物理隔离来强制独立性：每个角色只能看到 DAG 拓扑允许它看的输入，看不到其他任何东西。

一句话：**用多角色对抗 + 文献证据包 + 执行门禁，把“AI 做研究”从自由发挥变成有约束、可审计的审查流程。**

**当前版本：V0.7**（canonical gated runtime）

> 根目录中文入口：[README_CN.md](../README_CN.md)。本页是中文完整说明；英文入口在仓库根目录 `README.md`。

---

## 版本历史

### V0.7 — 当前（canonical gated runtime）
- **可验证 Deep Research 证据链**：Codex 显式调用 `$academic-research-suite`；Claude 显式调用已配置的 `academic-research-skills` plugin。L1 必须保存 Results/Discussion/Conclusion，L4 必须保存 Methods 与 review-search 回执，L8.5 必须保存论文验证结果；L10 注入定位摘录，L10b 必须引用 evidence ID。
- **L0 严格输入契约**：`normalize-l0-input` 将请求文件和显式数据位置规范化为可验证、可审计的 L0 contract；不从自然语言猜测路径、ID、决策或结论。
- **假说排序可靠性层（shadow mode）**：对显式候选集合执行 A/B 与 B/A 的公平 pairwise 判断；顺序翻转标记为 `UNCERTAIN`，并将排序、checkpoint、evidence event、正式决策分歧和失败审计隔离写入 `08_Audit/ranking/`。它绝不改变正式 gate、候选选择或 decision。

更早版本可通过 Git 历史查看；它们不是受支持的运行路径或活动模板规范。

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
| Academic Research runtime | `00_Preflight/deep_research_runtime.json`：CLI + Codex skill manifest 或 Claude plugin manifest | L1/L4/L8.5 证据获取 |
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

### 可验证 Deep Research（L1 / L4 / L8.5）

| 在哪个节点之前 | 步骤 | 做什么 |
|----------------|------|--------|
| L1 | 深度文献检索 | 通过 ARS 获取论文，保存可定位的 Results/Discussion/Conclusion 摘录 |
| L4 | 方法综述 | 保存研究论文的 Methods，并保存相关综述 Results/Conclusion 或零结果检索回执 |
| L8.5 | 结果后文献验证 | 用 L7/L8 的实际结果检索并保存支持/矛盾/未解决证据 |
| L7 | 代码搜索 | 搜 GitHub/Bioconductor/CRAN，复用已有 pipeline |

文献运行不再以手写摘要作为成功条件。每次运行的 CLI/skill receipt、来源数据库元数据响应、开放获取源文本（如可用）、定位摘录及 hash 都写入 `09_Literature_Database/evidence_packs/`；`assemble-context` 只接受通过该契约的 artifact。

### L8.5 文献验证节点

L7/L8 出结果后，L8.5（居里 的第二实例）基于**实际结果的关键词**去检索 PubMed/EuropePMC，验证结论是否与已发表文献一致。找到的论文加入可增长的文献数据库（`09_Literature_Database/`），跨轮复用，通过 Obsidian wikilink 引用。

### L0 依赖门禁（硬停止）

`preflight` / `check-deps` 检查所有必需依赖，任一缺失就退出码非零，**循环停止**。Academic Research 不接受环境变量自证：必须验证 `deep_research_runtime.json` 指定的 CLI，以及 Codex skill 或 Claude plugin manifest。

### 安全边界

- 只有 L7 图灵可以执行代码，而且只能在受控 workspace 与命令白名单内执行。
- 认知角色没有项目文件系统访问权；角色间只通过经过 schema 校验的 delta JSON 传递状态。
- 缺少依赖、文献证据或执行前置条件时，流程 fail-closed；不会用手写摘要或环境变量声明冒充证据。
- RLR 不会自动合并、发布、推送或替研究者作出 KEEP / REVISE / DOWNGRADE / DROP 之外的决策。

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
| L1 爱因斯坦 | frontmatter + L0 + 定位的 Results/Discussion/Conclusion | 可测试假设、主假设 | 生成假设 delta |
| L2 费曼 | frontmatter + L1 | 盲审攻击、混淆因素、诊断检验 | 不改状态 |
| L3 奥本海默 | L1 + L2 | 选中/拒绝假设及理由 | `triage-idea`；delta 成功写入后才可触发 shadow ranking |
| L4 费舍尔 | L1/L2/L3 + Methods/review evidence | 策略、脚本、参数、输出计划 | 提出分析方案 |
| L5 图基 | L4 + L2 | QC 检查点、失败规则、方法攻击 | 不改状态 |
| L6 奥本海默 | L4 + L5 | 分析方案批准/拒绝及修改 | `triage-method`；刻意不接入 ranking hook |
| L7 图灵 | L6 + L0 + 准备好的白名单 workspace | 脚本退出码、输出文件、关键结果 | 唯一允许执行代码的节点；先过 `execution-gate` |
| L8 居里 | L7 + L6 + frontmatter | 证据审计、可重复性检查、证据等级 | 进入 `AUDITED` |
| L8.5 居里 | L7 + L8 + 论文验证 evidence | 支持/矛盾审计和文献记录 | 进入 review |
| L9a 费曼 | L1 + L7 + L8 + L8.5 | 统计/逻辑证伪 | 与 L9b 并行，不能读取 L9b |
| L9b 达尔文 | L1 + L7 + L8 + L8.5 | 生物学解读和局限 | 与 L9a 并行，不能读取 L9a |
| L10a 乔布斯 | frontmatter + L8/L8.5/L9a/L9b + 定位 L1/L8.5 evidence | 价值评估和论文框架 | 不改状态 |
| L10b 奥本海默 | L10a + L8/L8.5/L9a/L9b + evidence IDs | 最终决策和可追溯理由 | `KEEP/REVISE/DOWNGRADE/DROP`；delta 成功写入后才可触发 shadow ranking |
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
   `deep_research.py` 负责 ARS receipt 与不可变论文证据；`ranking.py` 负责 advisory ranking artifact，绝不写入正式 decision 状态。

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
| `pre-research` | 打印旧研究提示或 L7 代码搜索提示（文献节点使用 `deep-research-run`） |
| `deep-research-run` | 调用配置的 Codex/Claude ARS 并持久化验证过的 evidence pack |
| `audit-literature-evidence` / `literature-report` | fail-closed 论文证据审计 / 定位证据报告 |
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

## 安装与最小验证

```bash
# 安装运行依赖
python -m pip install -r requirements.txt

# 可选：安装测试依赖
python -m pip install -r requirements-dev.txt

# 最小本地演示；真实研究流程仍会执行完整 L0 门禁
python research_loop_v04.py demo
python run_loop.py --help
```

真实研究流程还需要 Academic Research runtime、Zotero connector 和
Obsidian vault。缺少这些服务时，L0 会明确报错并停止，不会静默跳过。

---

## 文件结构

```
research_loop/
├── research_loop_v04.py          # 历史 CLI/import 兼容 shim，不是当前 engine 实现
├── src/research_loop/
│   ├── cli.py                    # 稳定 CLI 分发入口
│   ├── engine.py                 # 命令处理和编排操作
│   ├── api.py                    # 进程内 EngineAPI facade
│   ├── topology.py               # DAG 节点、转移和可见输入
│   ├── context.py                # Path B 上下文组装与 manifest
│   ├── gates.py                  # L0/L1/L7/L10 门禁和可追溯性校验
│   ├── delta.py                  # delta schema 和 candidate-owned 解析
│   ├── l0_contract.py            # L0 schema、validator、serializer、renderer
│   ├── l0_intake.py              # 规则型请求/数据 normalizer
│   ├── deep_research.py           # ARS runtime receipt、论文记录和 evidence pack
│   ├── providers/                # main-agent、command、headless、manual provider
│   ├── ranking.py                # shadow judge、Elo、checkpoint、evidence
│   ├── paths.py / yamlio.py      # 安全路径和 YAML/frontmatter I/O
│   ├── ledger.py / presearch.py  # pitfall/evidence ledger 与预研
│   └── errors.py                 # 类型化运行时错误
├── run_loop.py                   # 根目录兼容入口
├── src/run_loop.py               # canonical 循环运行器
├── src/orchestrator.py            # Provider 抽象
├── src/manage_literature_db.py    # 文献数据库
├── src/sync_to_obsidian.py        # Obsidian 同步
├── docs/MAIN_AGENT_RUN.md         # 主 agent 执行协议
├── docs/MAIN_AGENT_PROMPT.md      # 主 agent 启动提示词
├── docs/RUNNER.md                 # 运行模式 + StopPolicy
├── docs/DAG_TOPOLOGY.md           # DAG 依赖表
├── templates/layers/             # 15 个 layer 模板
├── templates/personas/           # 10 个人格模板
└── DemoProject_v03/              # 跟踪的示例项目
```

`research_loop_v04.py` 只是为了兼容历史测试和外部自动化而保留的文件名；
它把调用转发给 `research_loop.cli`，不再承载当前 engine 主体。新代码应直接导入
`research_loop.engine`、`research_loop.cli` 或 `research_loop.api`。

## 环境

- Python 3.13（标准库）+ PyYAML；R 4.6.0（L7 用）；Windows 11 / PowerShell。
- 必需外部依赖（L0 门禁）：Academic Research skill、Zotero、Obsidian vault（`$OBSIDIAN_VAULT`）。
- EverOS：可选，可配置端点。
