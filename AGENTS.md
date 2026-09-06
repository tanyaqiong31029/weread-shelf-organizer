# AGENTS.md — AI 协作规范（weread-shelf-organizer）

本仓库同时是已安装使用的 ZCode skill 与 GitHub 仓库。已接入工程化规范（pre-commit / ruff / mypy / gitleaks / CI）。AI agent 在本仓库工作时遵守以下约定。

## 项目概要
微信读书书架自动整理 Skill（Python）：`SKILL.md`（skill 指令文件）、`scripts/weread_shelf.py`（驱动 macOS 微信读书客户端的主脚本）、`scripts/plan.json`、`tests/`、`references/`、`examples/`、`docs/`。

## 常用命令
```bash
uvx ruff check . && uvx ruff format --check .    # lint（保持 0 问题）
uvx mypy .                                       # 类型检查（保持 0 错误）
python3 -m unittest discover -s tests            # 28 个离线回归测试，必须全绿
pre-commit run --all-files                       # 提交前全量自检
```

## 提交规范
- 提交信息：Conventional Commits（`<type>(<scope>)?: <subject>`），pre-commit 钩子强制执行。
- 钩子改了文件 → `git add -u` 重新提交；**禁止 --no-verify**。

## 行为红线（本仓库特殊，务必遵守）
- **SKILL.md 的指令语义不得改动**：它是 skill 的行为定义，改写措辞/结构都会改变 skill 行为。
- `scripts/weread_shelf.py` 会实际操控微信读书 Mac 客户端（真实用户数据）：行为逻辑改动必须先跑全部单测，且改动保持最小、逐条说明意图；纯 lint/format 级修复不受限。
- `references/`、`examples/`、`docs/` 为 skill 知识资产，除非任务明确要求，不要改写。
- 密钥绝不入库（gitleaks 已拦截）。
