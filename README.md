# weread-shelf-organizer

微信读书书架自动整理 Skill — 让 AI 帮你把书架整理得井井有条。

[![tests](https://github.com/tanyaqiong31029/weread-shelf-organizer/actions/workflows/test.yml/badge.svg)](https://github.com/tanyaqiong31029/weread-shelf-organizer/actions/workflows/test.yml)

一个 [ZCode](https://zcode.ai) / Claude Code 风格的 Agent Skill：通过本机微信读书 Mac 客户端的
登录凭据调用其书架接口，实现**分组的自动创建、书籍的批量归类、迁移后的自动核验**。

![demo](docs/demo.gif)

*真实演示：新书《鞋狗》入库 → 自动识别分类 → 归入「03 商业经济」→ 核验落位*

## ✨ 能力

- **全量重组** — 按你提供的分类表（Excel/CSV）一次性把整个书架归入新分组体系
- **从零分类** — 只给分组设想，AI 按平台分类 + 书名/作者逐本定类
- **增量整理** — 日常运行只处理新书/未分组书，适合每周定时任务
- **分组管理** — 自动创建缺失分组、清理迁移后清空的旧分组
- **安全核验** — 每批迁移后重新同步书架核验落位，报告未落位清单

## 📦 效果

真实书架 2924 本书、12 个目标分组的一次性重组：

| 分组 | 数量 | 分组 | 数量 |
|---|---|---|---|
| 01 成长学习 | 90 | 07 中文文学 | 320 |
| 02 语言写作 | 107 | 08 世界文学 | 564 |
| 03 商业经济 | 202 | 09 类型小说 | 617 |
| 04 历史社会 | 296 | 10 性别家庭 | 262 |
| 05 科技未来 | 84 | 11 人物传记 | 115 |
| 06 心智精神 | 242 | 12 艺术生活 | 25 |

2888 本一次性迁移，0 失败，全程约 4 分钟。

## 🚀 快速开始

### 1. 前置条件

- **macOS**：微信读书 Mac 客户端（App Store 安装，登录一次即可）— 凭据自动提取
- **Linux / Windows / CI**：设环境变量 `WEREAD_VID` / `WEREAD_SKEY`（可选 `WEREAD_V`）提供凭据
- python3（仅标准库，无第三方依赖）
- ZCode / Claude Code 等 Agent 环境（复制本目录到技能目录），或直接手动调用脚本

### 2. 安装为 Skill

```bash
# ZCode
git clone https://github.com/tanyaqiong31029/weread-shelf-organizer.git \
  ~/.agents/skills/weread-shelf-organizer

# Claude Code
git clone https://github.com/tanyaqiong31029/weread-shelf-organizer.git \
  ~/.claude/skills/weread-shelf-organizer
```

然后对 AI 说：

> 帮我把微信读书书架按这份表格整理一下 / 帮我整理微信读书书架的新书

### 3. 手动使用（不用 Agent 也行）

```bash
cd scripts

python3 weread_shelf.py creds                    # 验证凭据（自动启动客户端）
python3 weread_shelf.py plan \
    --rules ../examples/rules.example.json \
    -o plan.json --dry-run                       # 生成整理计划
python3 weread_shelf.py apply --plan plan.json   # 执行迁移 + 核验
python3 weread_shelf.py groups --purge-empty     # 清理空分组
```

分组规则见 `examples/rules.example.json`（12 分组示例 + 平台分类映射，改成分你自己的即可）。

## 🧠 工作原理

1. **凭据**：脚本启动本机微信读书 Mac 客户端，从其本地日志提取 `vid/skey`
   （只驻留内存，不落盘不回显）；skey 过期时自动重启客户端续期。
2. **接口**：调用客户端同款官方接口 —— `/shelf/sync` 同步、`/shelf/archive` 建组/移书、
   `/shelf/deleteArchive` 删分组。明细见 [references/api.md](references/api.md)。
3. **分类**：平台分类（如"经济理财-商业"）按规则映射到分组（完整命中置信度 0.95、
   主栏目命中 0.75，阈值可配）；映射不到或低于阈值的交给 AI 按书名/作者判断，
   再拿不准的保留"需复核"清单由你定夺。
4. **核验**：迁移后重新同步书架，逐本确认落在**预期分组**（而非任意目标分组）；
   任何错位都会显式报告。

## 🧪 测试

```bash
python3 -m unittest discover -s tests -v
```

14 个离线回归测试（全 mock、无网络）：classify 元数一致性、含待复核书的端到端 plan、
置信度阈值分流、正确分组核验、环境变量凭据、批次切分、基线解析等。
推送后由 GitHub Actions 自动执行。

## 🛡️ 安全设计

- 只移动「未分组」的书 — 你手动放入其他分组的书永远不会被碰
- 不删除书籍、不移出书架、不改变私密状态、不动专辑与文章收藏
- 删除分组只删空分组，且 `removeBooks: 0`（书永远保留在书架）
- 先 `--dry-run` 出计划再执行；每批 40 本、失败重试、迁移后核验

## ⚠️ 免责声明

本项目调用微信读书客户端内部接口（非官方开放 API），接口可能随版本更新而变化。
仅供学习与个人书架管理使用，请控制调用频率，勿用于任何商业用途或他人账号。
使用本项目产生的任何后果由使用者自行承担。

## License

[MIT](LICENSE)
