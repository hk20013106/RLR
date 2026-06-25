# RLR v0.5 拆分计划 — Claude Code 评估文档

## 背景

RLR (Research Loop Room) 是一个 DAG 驱动的多 agent 科研审议框架。
核心代码目前集中在单个文件 `research_loop_v04.py` 中，已增长到 2877 行 / 121KB。
随着功能迭代（预研钩子、双语 delta、Obsidian 同步、Turing workspace），单文件
已成为维护瓶颈：编辑易出错、diff 难审查、新人难定位。

本计划将 v0.4 拆分为 v0.5 模块化结构，目标是降低单文件复杂度，使每次编辑只碰
一个小文件（200-600 行），从而减少 patch 失败和误改。

---

## 当前文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| research_loop_v04.py | 2877 | 主控制器：CLI + DAG 定义 + 命令实现 + 报告生成 |
| run_loop.py | 771 | 循环驱动器：多轮编排 + StopPolicy + Review gate |
| sync_to_obsidian.py | 492 | Obsidian 同步：PDF 转 PNG + wikilink 嵌入 |
| orchestrator.py | 389 | provider 抽象层（Manual / Command） |
| research_loop_v03.py | ~2600 | v0.3 旧版（已标 deprecated，保留不动） |

外部依赖：
- run_loop.py `import research_loop_v04 as rl`（引用 DAG 元数据、helper 函数）
- sync_to_obsidian.py 独立运行，不 import 主控制器
- orchestrator.py 被 run_loop.py import

---

## 拆分方案

### 目标结构

```
D:\research_loop\
├── research_loop_v05.py       # 入口：CLI parser + main()（~200 行）
├── rlr_constants.py           # 纯数据：personas, DAG_NODES, schemas, transitions（~450 行）
├── rlr_utils.py               # 底层工具：yaml 解析、sha256、路径、状态读写（~350 行）
├── rlr_templates.py            # 静态模板字符串（~250 行）
├── rlr_dag_runtime.py          # DAG 循环引擎：next-step, pre-research, assemble-context, emit-delta（~600 行）
├── rlr_project_cmds.py         # 项目管理命令：new-project, decision, triage, gate, workspace, list, show, demo（~500 行）
├── rlr_report.py              # L10c 聚合报告 + 中英文翻译（~350 行）
├── run_loop.py                # 不变（更新 import 即可）
├── sync_to_obsidian.py        # 不变
├── orchestrator.py            # 不变
└── research_loop_v04.py       # 保留不动，标 deprecated
```

### 各模块职责

#### 1. rlr_constants.py（纯数据，无逻辑）
从 v0.4 中提取：
- AGENTS 列表（10 个人格名）
- PERSONA_TITLE 字典
- DECISION_TRANSITIONS 状态转换表
- DAG_NODES 列表（14 个节点定义）
- PRE_RESEARCH_MAP
- NODE_MAP（node_id -> node dict）
- DELTA_SCHEMAS（14 个 persona 的 delta schema）
- DELTA_PERSONA 映射
- FINAL_STATUSES 集合
- LAYER_TEMPLATE_FILE / PERSONA_TEMPLATE_FILE 路径映射

特点：无 import 依赖（只依赖标准库），被所有其他模块 import。

#### 2. rlr_utils.py（底层工具函数）
从 v0.4 中提取：
- _now, _stamp, _date, _slug — 时间/命名工具
- _candidate_file, _delta_file, _pre_research_file — 路径工具
- _sha256 — 文件哈希
- _audit_dir — 审计目录
- _input_alias — 输入别名映射
- _everos_scopes_for — EverOS 作用域
- _next_seq — 决策序号生成
- _yaml_value, _load_yaml_front, _save_yaml_front, _replace_field — YAML 读写
- strip_candidate_to_frontmatter — candidate 只读裁剪（路径 B 隔离核心）
- _require_status, _set_status — 状态检查/修改
- _append_decision — 决策日志追加
- _mkdirs — 目录创建
- _fmt_list, _fmt_dict, _empty_value_for_schema — 格式化工具
- _validate_delta — delta schema 校验

依赖：import rlr_constants

#### 3. rlr_templates.py（静态文本模板）
从 v0.4 中提取：
- _candidate_template_v03 — 新 candidate 的 Markdown 模板
- _index_template_v03 — 项目 index 模板
- _handoff_template — handoff 文档模板
- _decision_log_template — 决策日志模板
- _note_template — 笔记模板
- _preflight_template — L0 预检模板

特点：纯字符串，无逻辑，无 import 依赖。

#### 4. rlr_dag_runtime.py（DAG 循环引擎）
从 v0.4 中提取，这是整个系统的心脏：
- cmd_next_step — 计算下一个 DAG 节点，输出调度包 JSON
- cmd_pre_research — 生成 L1/L4/L7 预研提示
- cmd_assemble_context — 路径 B 隔离：拼装某节点的上下文，只嵌入 DAG 允许的 delta
- cmd_emit_delta — 校验 delta JSON 格式，写入 02_Agent_Notes

这四个函数互相紧密依赖，形成一个内聚循环：
  next-step -> assemble-context -> (agent 生成 delta) -> emit-delta -> next-step

依赖：import rlr_constants, rlr_utils

#### 5. rlr_project_cmds.py（项目管理命令）
从 v0.4 中提取：
- cmd_new_project — 建项目目录结构
- cmd_new_candidate — 建 candidate 文件
- cmd_preflight — L0 预检执行
- cmd_decision — 改状态
- cmd_triage_idea / cmd_triage_method — L3/L6 裁决
- cmd_execution_gate — L7 执行门禁（检查 skill_use_plan + input_manifest + 状态）
- cmd_prepare_turing_workspace — 路径 A：shutil.copy2 白名单文件到 workspace
- cmd_list — 列出所有项目和状态
- cmd_show — 查看某 candidate 详情
- cmd_demo — 跑 demo 项目

依赖：import rlr_constants, rlr_utils, rlr_templates

#### 6. rlr_report.py（报告生成）
从 v0.4 中提取：
- SECTION_TITLES_EN / SECTION_TITLES_CN — 报告章节标题
- _translate_delta_body_cn — delta 内容翻译
- _format_delta_body — delta 格式化（中英文）
- cmd_aggregate_report — L10c：读所有 delta，生成 FINAL_REPORT.md + FINAL_REPORT_CN.md

依赖：import rlr_constants, rlr_utils

#### 7. research_loop_v05.py（入口）
- build_parser() — argparse 构建，分发到各模块的 cmd_* 函数
- main() — 入口函数
- 从各模块 import cmd_* 函数并注册到 subparser

特点：不含业务逻辑，只做命令分发。约 200 行。

---

## 不改的部分

1. research_loop_v04.py 保留不动，标 deprecated（与 v0.3 同等对待）
2. run_loop.py 只需更新一行 import：`import research_loop_v04 as rl` -> `import rlr_constants as rl`（或新建一个 rlr_api.py 兼容层）
3. sync_to_obsidian.py 不变
4. orchestrator.py 不变
5. v0.3 / v0.4 现有项目数据（Yigene_WGCNA_v03 等）不变
6. DAG 拓扑、状态机、delta schema、路径 B 隔离逻辑——全部不变，只是换了文件位置
7. 15 个状态、14 个 DAG 节点、gate 机制——全部不变

---

## 拆分原则

1. **按职责切，不按行数切。** 每个模块解决一个明确的问题。
2. **单向依赖，无循环。** constants -> utils -> {dag_runtime, project_cmds, report} -> 入口。
3. **不动业务逻辑。** 拆分是纯机械移动，不修改任何函数实现。
4. **保持 CLI 接口不变。** 用户命令行用法完全不变（`python research_loop_v05.py next-step ...`）。
5. **v0.4 可回退。** 如果 v0.5 有问题，直接用 `python research_loop_v04.py` 即可。

---

## 依赖关系图

```
rlr_constants.py（无依赖）
       |
       v
rlr_utils.py（import constants）
       |
       +------------------+------------------+
       v                  v                  v
rlr_dag_runtime.py   rlr_project_cmds.py  rlr_report.py
  (import utils)       (import utils)     (import utils)
  (import constants)   (import constants)  (import constants)
  (import templates)   (import templates)
       |                  |                  |
       v                  v                  v
research_loop_v05.py（import 以上所有，注册 CLI）
```

---

## run_loop.py 兼容问题

当前 run_loop.py 有：
```python
import research_loop_v04 as rl
```

它引用了 rl 中的：
- rl.DAG_NODES
- rl.PRE_RESEARCH_MAP
- rl.NODE_MAP
- rl.DELTA_SCHEMAS
- 各种 _load_yaml_front 等 helper 函数

方案 A（推荐）：在 rlr_constants.py 和 rlr_utils.py 中保持这些名字不变，
run_loop.py 改为：
```python
from rlr_constants import DAG_NODES, PRE_RESEARCH_MAP, NODE_MAP, DELTA_SCHEMAS
from rlr_utils import _load_yaml_front, _set_status, ...
```

方案 B：建一个 rlr_api.py 兼容层，re-export 所有公共 API，
run_loop.py 只改一行 `import rlr_api as rl`。

---

## 验证清单

拆分完成后，Claude Code 需验证：

1. `python research_loop_v05.py --help` 正常输出，所有命令可见
2. `python research_loop_v05.py demo` 跑通 demo 项目，最终状态 KEEP
3. `python research_loop_v05.py next-step DemoProject_v05 <cand_id>` 输出正确
4. `python research_loop_v05.py assemble-context ... --node L1` 输出纯文本
5. `python research_loop_v05.py emit-delta ... --node L1 ...` schema 校验正常
6. `python run_loop.py --help` 正常（import 不报错）
7. `python run_loop.py print-main-agent-prompt DemoProject_v05 <cand_id>` 正常
8. v0.4 回归：`python research_loop_v04.py --version` 仍输出 0.4.0
9. 现有项目 Yigene_WGCNA_v03 仍可被 v0.5 读取（文件格式兼容）
10. 无循环 import（`python -c "import rlr_constants; import rlr_utils; ..."` 不报错）

---

## 评估请求

请 Claude Code 评估：

1. 拆分粒度是否合理（7 个模块是否太多/太少？）
2. 模块边界是否清晰（有没有函数放错地方？）
3. run_loop.py 兼容方案选 A 还是 B
4. 是否需要在拆分的同时修复已知问题（如 cmd_pre_research 未真正调用技能）
5. 拆分后是否应该删除目录中的临时文件（_tmp_*.json, _fix_*.py, _patch_*.py 等）
6. 是否应该将 research_loop_v03.py 也一并清理

---

## 技术约束

- Python 3.11+，无外部依赖（不用 pip install）
- Windows / PowerShell 环境
- 文件写入遵守 AGENTS.md 规则：大文件用 Set-Content here-string，不用 apply_patch
- R 脚本在 D:\R-HK\Seurat5_lib 下运行
- Obsidian vault 在 C:\Users\hk200\Documents\Obsidian Vault\ResearchLoop\

## 关键路径

- 主代码：D:\research_loop\research_loop_v04.py
- 循环驱动：D:\research_loop\run_loop.py
- Obsidian 同步：D:\research_loop\sync_to_obsidian.py
- Provider 层：D:\research_loop\orchestrator.py
- WGCNA 项目：D:\research_loop\Yigene_WGCNA_v03\
- R 脚本：D:\research_loop\scripts_wgcna_loop\
- AGENTS.md：C:\Users\hk200\.codex\AGENTS.md
- GitHub：https://github.com/hk20013106/RLR
