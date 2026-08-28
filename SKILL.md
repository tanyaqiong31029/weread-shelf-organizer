---
name: weread-shelf-organizer
description: 微信读书书架自动整理技能 — 全量重组、增量归类、自动创建分组、清理旧分组与迁移核验。当用户要求整理微信读书书架、按表格/规则给书籍分类、创建书架分组、每周定期整理书架、把新书归档到分组时使用。需要 macOS + 已登录的微信读书 Mac 客户端。
---

# 微信读书书架自动整理 (WeRead Shelf Organizer)

通过本机微信读书 Mac 客户端的登录凭据调用其官方书架接口，实现书架分组的批量整理：
全量重组（按用户提供的分类表）、增量归类（只整理新书/未分组书）、分组创建与清理、迁移后核验。

## 前置条件

- macOS + 已登录的**微信读书 Mac 客户端**（App Store 版；平时无需保持打开，脚本会自动启动）
- `python3`（标准库即可，无第三方依赖）
- 本技能目录下的 `scripts/weread_shelf.py`

**开始前必须先调用 `weread_shelf.py` 的子命令完成凭据验证（见工作流第 1 步）。**
凭据从客户端本地日志提取（vid/skey），只驻留内存，不落盘、不回显、不写入任何输出文件。

## 核心约束（安全红线）

1. **只移动「未分组」的书**。用户放入其他自定义分组的书一律跳过（脚本已内置该逻辑）。
2. **不删除书籍、不移出书架、不改变私密状态、不动专辑/文章收藏**。
3. 迁移后**必须核验落位**（`verify`），报告未落位清单。
4. 先 `--dry-run` 出计划，向用户展示或确认后再 `apply`。
5. 拿不准分类的书**宁可保留「需复核」也不要硬塞**，在报告中列出请用户定夺。

## 脚本用法

所有命令先 `cd` 到本技能 `scripts/` 目录（或用绝对路径）：

```bash
S=scripts/weread_shelf.py

python3 $S creds                      # 提取并验证凭据（失败→见"凭据失效"）
python3 $S sync -o snapshot.json      # 书架快照
python3 $S plan  --rules rules.json [--baseline base.csv] -o plan.json [--dry-run]
python3 $S apply --plan plan.json     # 批量迁移 + 自动核验
python3 $S review --decisions d.json  # 应用复核定类
python3 $S groups --list              # 列出分组
python3 $S groups --create "01 成长学习"
python3 $S groups --purge-empty       # 清理空分组
python3 $S verify --plan plan.json    # 独立核验
```

## 工作流

### 第 0 步：准备规则文件

分组规则 JSON（示例见 `examples/rules.example.json`）：

```json
{
  "groups": [
    {"name": "01 成长学习", "description": "个人成长、学习方法、教育、职场与考试"},
    {"name": "02 语言写作", "description": "语言学、翻译、外语、写作与学术研究"}
  ],
  "category_map": {
    "个人成长-成长方法论": "01 成长学习",
    "经济理财-商业": "03 商业经济",
    "精品小说": "09 类型小说"
  }
}
```

- `groups`：目标分组（name 需以两位数字前缀开头便于识别，description 用于 AI 复核时判断）
- `category_map`：微信平台分类 → 分组。支持完整分类（`经济理财-商业`）和主栏目（`精品小说`）
- `confidence`：命中置信度（完整命中默认 0.95，主栏目命中默认 0.75）
- `min_confidence`：自动迁移阈值（默认 0.6）。低于阈值的进复核清单；
  有候选但低于阈值时，`plan.json` 的 review 条目会带 `suggest` 字段供复核参考
- 可选 `--baseline base.csv`（`bookId,target_group` 两列）：用户已有分类表（如 Excel 导出）时，
  基线优先级最高（confidence=1.0）；无基线则纯靠 category_map + AI 复核

### 第 1 步：凭据验证

```bash
python3 $S creds
```

**凭据失效**（stderr 出现 FATAL）：提示用户打开微信读书 Mac 客户端确认登录（必要时重新扫码），用户确认后重试。不要绕过、不要重试超过 2 次。

**无 Mac 客户端的环境**（Linux/Windows/CI）：可设环境变量 `WEREAD_VID` / `WEREAD_SKEY`
（可选 `WEREAD_V`）提供凭据，脚本验证通过即用，无需客户端。

### 第 2 步：生成计划

```bash
python3 $S plan --rules rules.json -o plan.json --dry-run
```

产出 `plan.json`：
- `moves[]`：自动迁移清单（含去向、依据）
- `review[]`：低置信度待复核清单（书名/作者/平台分类/提示）
- `missing_groups`：不存在的目标分组
- `skipped_custom_groups`：用户自定义分组（不会触碰）

**分组缺失时先创建**：

```bash
python3 $S groups --create "01 成长学习"   # 逐个创建 missing_groups
```

### 第 3 步：AI 复核定类

读取 `plan.json` 的 `review[]`，逐本按以下优先级定类：

1. **平台分类**：`category` 字段语义 → 对照规则文件的 `description`
2. **书名与作者**：题材判断（小说/文学/社科/实用…）
3. **一致性**：同作者或同系列的书，跟随已迁移书籍的分组

写出 `decisions.json`：

```json
[{"bookId": "3300138205", "group": "01 成长学习"}]
```

- `group` 必须是规则文件中的分组名（中文名，不是代码）
- 确实拿不准的**不要写入**，让它留在复核清单里向用户汇报

### 第 4 步：执行迁移

```bash
python3 $S apply --plan plan.json        # 自动部分
python3 $S review --decisions decisions.json   # 复核部分
```

脚本自动：40 本/批、失败重试 3 次、迁移后重新同步核验落位。

### 第 5 步：收尾与报告

```bash
python3 $S groups --purge-empty    # 可选：清理迁移后清空的旧分组（仅空分组）
python3 $S verify --plan plan.json
```

向用户汇报（中文，简洁）：
- 本次迁移几本、复核定类几本、无法定类几本（列书名）
- 各分组最终数量
- 未落位/失败清单（如有）

## 三种典型场景

| 场景 | 做法 |
|------|------|
| **全量重组**（用户给出分类表/Excel） | 表格转 baseline CSV（bookId + 目标分组两列）→ `plan --baseline` → AI 补齐表中没有的书 → apply |
| **从零分类**（无表，只有分组设想） | 写 rules.json（分组 + category_map）→ plan → AI 对 review[] 全量定类 → apply |
| **增量整理**（日常新书归类） | 直接 `plan`（默认只处理未分组书）→ apply → review |

## 参考文件

- `references/api.md` — 接口明细、请求头、错误码、常见问题
- `examples/rules.example.json` — 12 分组示例规则（可直接改用）
- `tests/` — 离线回归测试（`python3 -m unittest discover -s tests`，全 mock 无网络）；
  改动分类/迁移逻辑后必须先跑通测试
