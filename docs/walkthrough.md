# 安全迁移演练（Reorganize Walkthrough）

以一次真实场景为例：把两个旧榜单分组按分类表打散重排。全程四步，
每一步都有确认点，任何一步不满意都可以停下。

> 前提：已安装 Skill 并通过 `weread-shelf creds` 验证；已准备好基线 CSV
> （`bookId,target_group` 两列，来自你的分类表）。

## 第 1 步：生成计划（只读，不改动书架）

```bash
python3 weread_shelf.py plan \
    --rules examples/rules.example.json \
    --baseline my_base.csv \
    --reorganize --source-group "探照灯好书小说2,豆瓣评分9.0以上的书籍" \
    -o plan.json --dry-run
```

输出（节选）：

```
[00:12:29] 待整理: 未分组 3 本 + 白名单来源分组 491 本
[00:12:29] 计划: 自动迁移 402 本, 待复核 92 本, 跳过自定义分组 0 本 → plan.json
```

`plan.json` 关键字段：

| 字段 | 含义 |
|---|---|
| `plan_id` | 本份计划的唯一标识（审计/幂等判断） |
| `shelf_hash` | 计划时点书架归组状态哈希——之后书架若有变动，哈希即不同 |
| `moves[].from` | 每本书的来源分组；`null` 表示计划时未分组 |
| `source_snapshot` | 白名单来源分组的书籍清单（审计快照） |
| `review[]` | 置信度不足的书，交给你/AI 定类 |

**人工确认点 ①**：打开 `plan.json`，抽查 `moves` 的去向是否符合预期，
确认 `source_snapshot` 里没有你不想动的分组。

## 第 2 步：复核定类（AI 或人工）

把 `review[]` 里的书逐本定类，写成 `decisions.json`
（`from` 从 review 条目原样复制，重组模式必带）：

```json
[
  {"bookId": "3300024289", "group": "04 历史社会", "from": "探照灯好书小说2"},
  {"bookId": "25615385",   "group": "06 心智精神", "from": "豆瓣评分9.0以上的书籍"}
]
```

拿不准的书不要写进去——它们会保留在原分组，并在最终报告里列出。

## 第 3 步：确认执行（--yes 双重确认）

```bash
python3 weread_shelf.py apply --plan plan.json --yes --json-report report.json
python3 weread_shelf.py review --decisions decisions.json --json-report report_review.json
```

- 不加 `--yes` 时，含「来自已有分组」书籍的 apply 会以退出码 3 拒绝执行；
- 执行前脚本会**重新同步书架**，逐本核对当前分组与计划一致，
  不符自动跳过（期间你手动移动过的书不会被错误处理）；
- 每批 40 本，429/5xx/网络抖动自动指数退避重试。

## 第 4 步：核验与收尾

```bash
python3 weread_shelf.py verify --plan plan.json
python3 weread_shelf.py groups --purge-empty     # 可选: 清理已清空的旧分组
```

`report.json` 结构（自动化可消费）：

```json
{
  "command": "apply",
  "plan_id": "a1b2c3d4e5f6",
  "batch_id": "0f1e2d3c",
  "planned": 402,
  "moved": ["..."],
  "failed": [],
  "stale": [],
  "wrong": []
}
```

退出码：`0` 成功 · `1` 有失败/错位 · `2` 凭据失效 · `3` 未加 `--yes`。

## 中途出错了怎么办

- **部分成功**：`report.json` 的 `moved/failed/stale` 明确区分三类状态。
  直接重新 `plan`（书架当前状态为准）→ 已归位的书自动跳过，只补未完成的；
- **凭据过期（退出码 2）**：打开微信读书 Mac 客户端重新登录后重试；
- **后悔了**：书没有删、没有移出书架，只是分组变了——按新基线再 `plan` 一次即可整体搬回。
