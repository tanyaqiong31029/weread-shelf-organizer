# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/) 规范，版本号遵循语义化版本。

## [1.2.0] - 2026-09-06

### 新增
- **网络层指数退避**: 429/5xx/网络超时按指数退避+抖动自动重试, 遵循 Retry-After;
  其他 4xx 快速失败 (http_json 层, 全命令受益)
- **审计标识**: plan 生成 plan_id 与 shelf_hash(计划时点归组状态哈希);
  apply/review 每次执行生成 batch_id, 报告新增 batches 批次摘要
- **pyproject 包元数据**: 可 pip 安装/升级, 提供 `weread-shelf` CLI 入口
  (requires-python >=3.9, venv 实测通过)
- **安全迁移演练文档**: docs/walkthrough.md 完整展示
  plan --dry-run → 人工审阅 → apply --yes → verify 全流程

### 变更
- 批量迁移返回值增加批次摘要 (_do_moves → 三元组)

## [1.1.1] - 2026-09-02

### 修复
- 系统分组「归档」(archiveId=1) 视同未分组——客户端会把未分组书放入该容器承载，
  此前执行前状态校验会误跳过这部分书的迁移；附 2 项回归测试
- 示例规则: 精品小说-社会小说 改向 09 类型小说（原 →08 世界文学，
  会把陈彦、豆豆等中国当代社会小说误导向外国文学）

### 补充
- 示例规则补充 8 条实战高频映射（漫画类、计算机-人工智能、励志/人生哲学等）
- api.md 补充归档容器行为说明与 shelf/add、shelf/delete 接口参考
- 仓库文档措辞统一：「全量重组」→「书架重组（白名单确认）」

## [1.1.0] - 2026-08-30

### 安全
- 重组模式做实：`plan --reorganize --source-group "白名单"` 只迁移白名单来源分组内的书，
  计划记录每本书的来源（`from`）与来源分组快照（`source_snapshot`）；
  含重组迁移的 `apply` 必须加 `--yes` 人工确认（退出码 3）
- `apply`/`review` 执行前重新同步书架，逐本校验「当前分组 == 计划来源分组」，
  状态不符自动跳过——过期或被篡改的计划无法绕过安全线

### 修复
- `classify()` 返回值元数不一致导致 plan 在首本待复核书处崩溃（v1.0.0 严重缺陷）
- `apply`/`review` 存在迁移失败或核验错位时以非零退出码结束（此前误报成功）
- 脚本日志脱敏 vid；裸 `open()` 全部改为上下文管理器

### 新增
- `--json-report`：apply/review 输出结构化 moved/failed/stale/wrong 报告，供定时任务判断成败
- 置信度按匹配类型取值（完整命中/主栏目命中可配），`min_confidence` 阈值生效，
  低于阈值的进复核清单并附候选建议
- verify 升级为校验「预期分组」而非「任意目标分组」
- 环境变量凭据路径 `WEREAD_VID`/`WEREAD_SKEY`（Linux/Windows/CI 可用）
- 26 项离线回归测试 + GitHub Actions CI

## [1.0.0] - 2026-08-28

- 首次发布：全量重组、增量归类、分组创建/清理、迁移核验
- 12 分组示例规则、接口参考文档、演示动图
