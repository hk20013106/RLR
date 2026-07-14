# Research Loop Room (RLR) — 中文介绍

RLR 是一个**证据门禁的科学研究审查框架**：把一个研究问题组织成 15 个节点（L0 → L10c），由相互隔离的角色依次完成预检、假设、盲审、方法设计、受控执行、证据审计、文献验证、证伪和最终决策。

核心原则是两种隔离：认知角色只看到 DAG 允许的结构化输入；唯一执行代码的 L7 图灵只使用受控 workspace 和命令白名单。缺少依赖、定位证据或门禁前置条件时，流程 fail-closed，不把手写摘要或环境变量声明当作证据。

当前版本：**V0.7（canonical gated runtime）**

## 快速入口

- [中文完整说明](docs/README_CN.md)
- [English README](README.md)
- 运行入口：`python run_loop.py run PROJECT CAND`

## 安装与最小验证

```bash
# 安装运行依赖
python -m pip install -r requirements.txt

# 可选：安装测试依赖
python -m pip install -r requirements-dev.txt

# 最小本地演示，不代表真实研究流程已通过全部门禁
python research_loop_v04.py demo
python research_loop_v04.py --help
python run_loop.py --help
```

真实研究流程仍需要 Academic Research runtime、Zotero connector 和
Obsidian vault。L0 会严格检查这些依赖；缺少时会给出错误并停止，不会
静默跳过或伪造通过。

V0.7 的深度研究门禁覆盖 L1、L4 和 L8.5；每次文献运行都保存可定位、可复核的 evidence pack。L0 还会校验严格的输入契约；可选的 Hypothesis Ranking Reliability Layer 只生成 advisory artifact，不改变正式 gate 或决策。

## 明确边界

- 只有 L7 可以执行代码，所有其他角色都是认知审查角色。
- 角色之间不共享完整上下文；状态只通过 schema 校验的 delta JSON 传递。
- RLR 不自动推送、合并、发布或绕过门禁；最终 KEEP / REVISE / DOWNGRADE / DROP 仍需按流程审查。

完整的 DAG、角色契约、依赖门禁、命令和文件结构请参阅[中文完整说明](docs/README_CN.md)或英文 README。
