# RLR v0.5 拆分计划 — Claude Code 评估文档

> 用途：交给 Claude Code 审查拆分方案的合理性，指出风险或更优方案，然后执行。
> 日期：2026-06-25
> 当前版本：v0.4.0
> 目标版本：v0.5.0

---

## 1. 背景

`research_loop_v04.py` 已膨胀到 2877 行、121KB。所有逻辑集中在一个文件里，
导致：

- apply_patch 对大文件/中文 Markdown 失败率极高（已记录在 AGENTS.md）
- 每次改一个函数要碰整个文件，编辑工具更容易出错
- 函数边界不清，改动难以隔离
- 已有两个外部文件（run_loop.py 771 行、sync_to_obsidian.py 492 行）依赖
  `import research_loop_v04 as rl`，单文件部署的优势已不存在

## 2. 当前文件结构（按行号区块）

| 区块 | 行范围（约） | 行数 | 内容 |
|------|-------------|------|------|
| 常量定义 | 46-440 | 394 | personas, DAG_NODES, PRE_RESEARCH_MAP, schemas, transitions |
| 小工具函数 | 437-720 | 283 | yaml 解析、sha256、路径、状态读写、delta 校验 |
| 模板字符串 | 722-1010 | 288 | candidate/index/handoff/decision/preflight 模板 |
| DAG 运行时命令 | 1012-1588 | 576 | next-step, pre-research, assemble-context, emit-delta |
| 项目管理命令 | 1589-2055 | 466 | new-project, new-candidate, decision, triage, gate, workspace, list, show, demo |
| Obsidian sync | 2057-2235 | 178 | cmd_obsidian_sync |
| 报告生成 | 2238-2553 | 315 | aggregate-report + 中英翻译 + 格式化 |
| CLI parser + main | 2556-2877 | 321 | argparse 构建 + main 入口 |

## 3. 拆分方案

```
D:\research_loop\
├── research_loop_v05.py       # 入口 + CLI parser（~320 行）
├── rlr_constants.py           # 纯数据：personas, DAG, schemas, transitions（~400 行）
├── rlr_utils.py               # 底层工具：yaml/sha256/路径/状态读写/delta校验（~300 行）
├── rlr_templates.py            # 静态模板字符串（~290 行）
├── rlr_dag_runtime.py          # DAG 循环引擎：next-step, pre-research, assemble-context, emit-delta（~580 行）
├── rlr_project_cmds.py         # 项目管理：new-project, decision, triage, gate, workspace, list, show, demo（~470 行）
├── rlr_report.py              # 报告生成：aggregate-report + 中英翻译（~320 行）
├── run_loop.py                 # 已存在，需更新 import（~770 行）
├── orchestrator.py             # 已存在，需更新 import（~390 行）
├── sync_to_obsidian.py         # 已存在，独立（~490 行）
└── templates/                  # 不动
```

## 4. 各模块职责说明

### research_loop_v05.py — 入口
- argparse 构建（build_parser）
- main() 入口
- 调用各模块的 cmd_* 函数
- 不含任何业务逻辑

### rlr_constants.py — 纯数据
- AGENTS（10 个人格列表）
- PERSONA_TITLE
- DAG_NODES（14 个节点定义）
- PRE_RESEARCH_MAP
- DELTA_SCHEMAS
- DELTA_PERSONA
- DECISION_TRANSITIONS
- STATUS_FLOW
- FINAL_STATUSES
- NODE_MAP, LAYER_TEMPLATE_FILE, PERSONA_TEMPLATE_FILE
- 无函数，无逻辑，纯常量

### rlr_utils.py — 底层工具
- _load_yaml_front / _save_yaml_front / _replace_field
- strip_candidate_to_frontmatter
- _sha256 / _now / _stamp / _date / _slug
- _candidate_file / _delta_file / _audit_dir / _pre_research_file
- _set_status / _append_decision / _require_status
- _next_seq
- _mkdirs
- _validate_delta / _empty_value_for_schema
- _fmt_list / _fmt_dict
- RLRError 异常类

### rlr_templates.py — 模板字符串
- _candidate_template_v03
- _index_template_v03
- _handoff_template
- _decision_log_template
- _note_template
- _preflight_template
- 纯字符串，无逻辑

### rlr_dag_runtime.py — DAG 循环引擎
- cmd_next_step
- cmd_pre_research
- cmd_assemble_context
- cmd_emit_delta
- 这四个是主 agent 循环调用的核心命令

### rlr_project_cmds.py — 项目管理命令
- cmd_new_project
- cmd_new_candidate
- cmd_preflight
- cmd_decision
- cmd_route
- cmd_triage_idea
- cmd_triage_method
- cmd_execution_gate
- cmd_prepare_turing_workspace
- cmd_list
- cmd_show
- cmd_demo
- cmd_note
- cmd_obsidian_sync

### rlr_report.py — 报告生成
- SECTION_TITLES_EN / SECTION_TITLES_CN
- _translate_delta_body_cn
- _format_delta_body
- cmd_aggregate_report

## 5. 依赖关系

```
research_loop_v05.py
  ├── rlr_constants        （无外部依赖）
  ├── rlr_utils            （依赖 rlr_constants）
  ├── rlr_templates         （依赖 rlr_constants）
  ├── rlr_dag_runtime      （依赖 rlr_constants, rlr_utils）
  ├── rlr_project_cmds     （依赖 rlr_constants, rlr_utils, rlr_templates）
  └── rlr_report           （依赖 rlr_constants, rlr_utils）

run_loop.py
  └── import research_loop_v05 as rl  （当前 import research_loop_v04）

orchestrator.py
  └── 无直接 import controller（通过 subprocess 调用 CLI）

sync_to_obsidian.py
  └── 独立，无 import controller
```

无循环依赖。

## 6. 不改的部分

- 14 个 DAG 节点定义、状态机、gate 逻辑不变
- delta schema 不变
- CLI 命令名和参数不变
- sync_to_obsidian.py 不动
- templates/ 目录不动
- 现有项目数据（Yigene_WGCNA_v03/ 等）不动
- research_loop_v04.py 保留不删（标 deprecated），现有项目仍可跑

## 7. 拆分步骤

1. 创建 rlr_constants.py，把所有常量移入，验证 `python -c "import rlr_constants"`
2. 创建 rlr_utils.py，移入工具函数，验证 import
3. 创建 rlr_templates.py，移入模板字符串，验证 import
4. 创建 rlr_dag_runtime.py，移入四个核心命令函数，验证 import
5. 创建 rlr_project_cmds.py，移入项目管理命令，验证 import
6. 创建 rlr_report.py，移入报告生成，验证 import
7. 创建 research_loop_v05.py，写入 CLI parser + main，import 所有模块
8. 运行 `python research_loop_v05.py --help`，确认所有命令可见
9. 运行 `python research_loop_v05.py demo`，确认 demo 正常
10. 运行 `python research_loop_v05.py next-step DemoProject_v03 <cand_id>`，确认 DAG 调度正常
11. 更新 run_loop.py 的 import 为 research_loop_v05
12. 运行 `python run_loop.py --help`，确认正常
13. 更新 README.md、MAIN_AGENT_RUN.md、MAIN_AGENT_PROMPT.md、RUNNER.md 中的版本号

## 8. 验证标准

- `python research_loop_v05.py --help` 输出所有命令
- `python research_loop_v05.py demo` 正常生成 demo 项目并走完 DAG
- `python research_loop_v05.py next-step DemoProject_v03 <cand>` 输出正确节点
- `python research_loop_v05.py assemble-context DemoProject_v03 <cand> --node L1` 输出隔离上下文
- `python run_loop.py --help` 正常
- 现有 `python research_loop_v04.py --help` 仍然正常（v0.4 保留）
- 所有模块可独立 import 无报错

## 9. 风险

- 拆分过程中可能遗漏某些函数的全局变量或闭包依赖（需检查函数内是否引用了模块级变量）
- argparse 的 subparser 注册分散在各模块时需要统一绑定
- run_loop.py 直接 `import research_loop_v04 as rl` 并引用了 rl.DAG_NODES、rl.PRE_RESEARCH_MAP 等常量，更新 import 后需确认引用路径

## 10. 给 Claude Code 的问题

1. 这个拆分粒度是否合理？是否太细或太粗？
2. rlr_dag_runtime 和 rlr_project_cmds 是否应该合并？
3. 是否有更好的模块划分方式？
4. 拆分顺序是否需要调整？
5. 是否应该在拆分的同时加入单元测试？

---

## 附：当前文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| research_loop_v04.py | 2877 | 主控制器（待拆分） |
| run_loop.py | 771 | 循环驱动器 |
| sync_to_obsidian.py | 492 | Obsidian 同步 |
| orchestrator.py | 389 | provider 层 |
| research_loop_v03.py | — | v0.3 旧版（deprecated） |
| templates/ | — | persona + layer 模板 |
| scripts_wgcna_loop/ | — | WGCNA R 脚本 |
| Yigene_WGCNA_v03/ | — | 实际分析项目 |
| DemoProject_v03/ | — | demo 项目 |
