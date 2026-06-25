# RLR v0.5 拆分计划 — Claude Code 评估文档

> 生成时间: 2026-06-25
> 当前版本: v0.4.0
> 目标: 将 research_loop_v04.py (2877 行, 121KB) 拆分为多个职责单一的模块

---

## 1. 现状

### 1.1 文件规模

| 文件 | 行数 | 大小 | 职责 |
|------|------|------|------|
| research_loop_v04.py | 2877 | 121KB | 全部：常量 + 工具 + 模板 + 所有命令 + 报告 + CLI |
| run_loop.py | 771 | 33KB | 多轮驱动 + StopPolicy + Review gate |
| sync_to_obsidian.py | 492 | 21KB | Obsidian 同步 + PDF转PNG |
| orchestrator.py | 389 | 15KB | Provider 抽象 (Manual/Command) |

### 1.2 核心痛点

单文件 2877 行导致：

- apply_patch 对大文件成功率极低（反复失败，已记录在 AGENTS.md）
- MCP `__edit` 工具也因文件过大频繁超时
- 每次修改一处都要碰整个文件，编辑失败 → 重试 → 浪费 token
- 函数间耦合不明显，改一处难以判断影响范围

### 1.3 research_loop_v04.py 内部结构

| 区块 | 行号 | 行数(约) | 内容 |
|------|------|----------|------|
| 常量定义 | 46-440 | ~400 | personas, DAG_NODES, PRE_RESEARCH_MAP, schemas, transitions |
| 小工具函数 | 437-720 | ~280 | yaml解析, sha256, 路径, 状态读写, delta校验 |
| 模板字符串 | 720-1010 | ~290 | candidate/index/handoff/decision/preflight/note 模板 |
| DAG运行时命令 | 1012-1590 | ~580 | next-step, pre-research, assemble-context, emit-delta |
| 项目管理命令 | 1591-2055 | ~460 | new-project, new-candidate, decision, triage, gate, workspace, list, show, demo |
| Obsidian同步 | 2057-2235 | ~180 | cmd_obsidian_sync |
| 聚合报告 | 2238-2555 | ~320 | L10c报告生成 + 中英文翻译 |
| CLI parser | 2556-2721 | ~165 | argparse 构建 + main() |

---

## 2. 拆分方案

### 2.1 目标文件结构

```
D:\research_loop\
├── research_loop_v05.py       # 入口 (CLI parser + main, ~170行)
├── rlr_constants.py            # 纯数据：personas, DAG, schemas, transitions (~450行)
├── rlr_utils.py                # 底层工具：yaml, sha256, 路径, 状态读写, delta校验 (~350行)
├── rlr_templates.py             # 静态模板字符串 (~300行)
├── rlr_dag_runtime.py          # DAG循环引擎：next-step, pre-research, assemble-context, emit-delta (~600行)
├── rlr_project_cmds.py         # 项目管理命令 (~480行)
├── rlr_report.py               # 聚合报告 + 中英文翻译 (~500行)
├── rlr_obsidian.py             # Obsidian同步 (从cmd_obsidian_sync抽出, ~200行)
├── run_loop.py                 # 保留不动，改 import 为 research_loop_v05
├── orchestrator.py             # 保留不动
├── sync_to_obsidian.py         # 保留不动（独立脚本，已可用）
└── templates/                  # 保留不动
```

### 2.2 各模块职责说明

#### research_loop_v05.py — 入口

只做两件事：
1. 构建 argparse parser
2. 把命令行参数分发到对应模块的 cmd_xxx 函数

不含任何业务逻辑。所有 `cmd_xxx` 函数从各自模块 import 进来，注册到 subparser。

#### rlr_constants.py — 纯数据

完全静态，不含函数，只有数据结构：

- `AGENTS` — 10 个人格名列表
- `PERSONA_TITLE` — 人格标题映射
- `DAG_NODES` — 14 个 DAG 节点定义
- `PRE_RESEARCH_MAP` — 3 个预研钩子配置
- `DELTA_SCHEMAS` — 每个 persona 的 delta JSON schema
- `DELTA_PERSONA` — node → persona 映射
- `DECISION_TRANSITIONS` — 15 个状态转换规则
- `FINAL_STATUSES` — 终态集合
- `NODE_MAP`, `LAYER_TEMPLATE_FILE`, `PERSONA_TEMPLATE_FILE` — 派生映射

#### rlr_utils.py — 底层工具

被所有其他模块调用的通用函数：

- `_load_yaml_front(path)` — 读 candidate YAML frontmatter
- `_save_yaml_front(path, fm)` — 写 YAML frontmatter
- `_replace_field(path, key, value)` — 改单个字段
- `strip_candidate_to_frontmatter(path)` — 只返回 frontmatter dict（路径B隔离核心）
- `_sha256(path)` — 文件哈希
- `_now()`, `_stamp()`, `_date()`, `_slug(s)` — 时间/命名工具
- `_candidate_file(project_dir, cand_id)` — 定位 candidate 文件
- `_delta_file(project_dir, delta_key)` — 定位 delta 文件
- `_set_status(project_dir, cand_id, status)` — 改状态
- `_require_status(fm, cand_id, expected)` — 状态守卫
- `_append_decision(...)` — 追加 decision log
- `_validate_delta(schema, data)` — delta JSON 校验
- `_mkdirs(project_dir)` — 建项目目录结构

#### rlr_templates.py — 静态模板

纯字符串，不含逻辑：

- `_candidate_template_v03(...)` — candidate 文件模板
- `_index_template_v03(...)` — 项目 index 模板
- `_handoff_template(...)` — handoff 模板
- `_decision_log_template(...)` — decision log 模板
- `_note_template(...)` — note 模板
- `_preflight_template(...)` — preflight 模板

#### rlr_dag_runtime.py — DAG 循环引擎

整个系统运行时反复执行的四个命令：

- `cmd_next_step(args)` — 查 DAG 表，输出下一个节点的调度包 JSON
- `cmd_pre_research(args)` — 生成预研提示（L1/L4/L7）
- `cmd_assemble_context(args)` — 按 DAG 拓拼装隔离上下文（路径B核心）
- `cmd_emit_delta(args)` — 校验 delta JSON schema 并写入磁盘

这四个函数形成内聚循环：next-step → assemble-context → (agent生成delta) → emit-delta → next-step

#### rlr_project_cmds.py — 项目管理命令

不参与循环的 CLI 命令：

- `cmd_new_project(args)` — 建项目目录
- `cmd_new_candidate(args)` — 建 candidate 文件
- `cmd_preflight(args)` — L0 预检
- `cmd_decision(args)` — 改状态
- `cmd_triage_idea(args)` — L3 假设裁决
- `cmd_triage_method(args)` — L6 方法批准
- `cmd_execution_gate(args)` — L7 执行门禁
- `cmd_prepare_turing_workspace(args)` — 准备 Turing workspace（路径A）
- `cmd_list(args)` — 列项目
- `cmd_show(args)` — 查状态
- `cmd_demo(args)` — 跑 demo

#### rlr_report.py — 聚合报告

L10c Linnaeus 的全部逻辑：

- `cmd_aggregate_report(args)` — 读所有 delta，生成 FINAL_REPORT.md
- `SECTION_TITLES_EN` / `SECTION_TITLES_CN` — 报告章节标题
- `_translate_delta_body_cn(text)` — delta 中文翻译
- `_format_delta_body(delta_key, delta, lang)` — delta 格式化（中/英）

#### rlr_obsidian.py — Obsidian 同步

从原 `cmd_obsidian_sync` 抽出：

- `cmd_obsidian_sync(args)` — 复制 delta + 报告到 vault，生成 wikilink 索引

---

## 3. 依赖关系

```
research_loop_v05.py (入口)
  ├── imports rlr_dag_runtime    (cmd_next_step, cmd_pre_research, cmd_assemble_context, cmd_emit_delta)
  ├── imports rlr_project_cmds   (cmd_new_project, cmd_decision, ...)
  ├── imports rlr_report         (cmd_aggregate_report)
  └── imports rlr_obsidian       (cmd_obsidian_sync)

rlr_dag_runtime.py
  ├── imports rlr_constants      (DAG_NODES, PRE_RESEARCH_MAP, DELTA_SCHEMAS, NODE_MAP, ...)
  ├── imports rlr_utils          (_load_yaml_front, _delta_file, _validate_delta, _pre_research_file, ...)
  └── imports rlr_templates      (无直接依赖，但 assemble_context 读模板文件路径用 constants)

rlr_project_cmds.py
  ├── imports rlr_constants
  ├── imports rlr_utils
  └── imports rlr_templates      (_candidate_template_v03, _index_template_v03, ...)

rlr_report.py
  ├── imports rlr_constants      (DAG_NODES, DELTA_PERSONA, ...)
  └── imports rlr_utils          (_delta_file, _load_yaml_front, ...)

rlr_obsidian.py
  ├── imports rlr_constants
  └── imports rlr_utils

run_loop.py
  └── imports research_loop_v05 as rl   (改当前 import research_loop_v04 as rl)

orchestrator.py
  └── 无变化（不直接 import controller）
```

无循环依赖。依赖方向单一：入口 → 命令模块 → 工具/常量/模板。

---

## 4. 不可改动的部分

以下行为必须保持不变，拆分是纯机械重构：

1. **CLI 接口**：所有 `python research_loop_v0X.py <command> <args>` 的命令名、参数名、输出格式不变
2. **DAG 拓扑**：14 个节点、依赖关系、状态转换不变
3. **Delta schema**：每个 persona 的字段定义不变
4. **路径B隔离逻辑**：`strip_candidate_to_frontmatter` 只返回 frontmatter dict，不返回 body
5. **Turing workspace**：`shutil.copy2` + 同盘临时目录，不用 os.link
6. **状态机**：15 个状态 + 转换规则不变
7. **预研钩子**：PRE_RESEARCH_MAP 的三处定义不变（L1/L4/L7）
8. **双语文报告**：FINAL_REPORT.md + FINAL_REPORT_CN.md 的生成逻辑不变

---

## 5. 验证计划

拆分完成后逐项验证：

1. `python research_loop_v05.py --help` 输出与 v04 完全一致
2. `python research_loop_v05.py demo` 跑通完整 demo，状态走到 KEEP
3. `python research_loop_v05.py next-step <project> <cand>` 输出正确的 DAG 节点
4. `python research_loop_v05.py assemble-context <project> <cand> --node L1` 输出隔离上下文
5. `python research_loop_v05.py emit-delta <project> <cand> --node L1 --persona Einstein --file <delta>` 校验通过
6. `python research_loop_v05.py aggregate-report <project> <cand>` 生成中英文报告
7. `python run_loop.py --help` 正常（改 import 后）
8. `python run_loop.py run DemoProject_v03 <cand> --dry-run` 正常
9. 现有 WGCNA 项目 `Yigene_WGCNA_v03` 的 delta 文件不被改动
10. `git diff` 只新增 .py 文件 + 改 run_loop.py 的 import 行，不碰其他文件

---

## 6. 实施建议

### 6.1 顺序

1. 先建 `rlr_constants.py`（纯数据搬运，零风险）
2. 再建 `rlr_utils.py`（函数搬运，验证 import 不报错）
3. 建 `rlr_templates.py`（字符串搬运）
4. 建 `rlr_dag_runtime.py`（搬 4 个核心函数）
5. 建 `rlr_project_cmds.py`（搬项目管理函数）
6. 建 `rlr_report.py`（搬报告函数）
7. 建 `rlr_obsidian.py`（搬同步函数）
8. 最后建 `research_loop_v05.py`（入口 + CLI parser）
9. 改 `run_loop.py` 的 import 行
10. 跑验证计划

### 6.2 注意事项

- 所有以 `_` 开头的函数（如 `_load_yaml_front`）搬走后需去掉下划线前缀改为公开函数，或保持私有在模块内用。建议保持私有，跨模块调用时通过模块名访问：`rlr_utils._load_yaml_front()`。或者统一去掉下划线改为公开 API。
- `rlr_constants.py` 中 `NODE_MAP` 和 `LAYER_TEMPLATE_FILE` 是从 `DAG_NODES` 派生的，需确保在常量模块内完成派生。
- 原 v04 文件保留不动，不删除，不覆盖。v05 是新文件。
- AGENTS.md 的文件写入规则适用于本次拆分：大文件用 Set-Content here-string，不用 apply_patch。

---

## 7. 不拆的理由（供 Claude Code 权衡）

- 单文件 `python research_loop_v04.py` 一条命令就能跑，拆分后需 `python research_loop_v05.py` 但内部多文件 import
- 对终端用户来说 CLI 接口不变，拆分是内部重构，用户无感
- 拆分本身不增加功能，只降低维护成本

但考虑到 v04 已经 2877 行且还在增长（v0.5 计划增加文献检索节点），不拆只会越来越难改。
