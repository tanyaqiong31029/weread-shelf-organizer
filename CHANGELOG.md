# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/) 规范，版本号遵循语义化版本。

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
