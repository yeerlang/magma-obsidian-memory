## 升级指南（从旧版本迁移）

如果你之前部署了 MAGMA（commit 早于 2026-07-01），参见 **[docs/migration.md](docs/migration.md)**。5 步完成：`git pull` → 清理存量边 → 重启 → 验证 → 注册定时任务。

旧版已知问题：VectorDB 重启后丢失、边爆炸数百倍、实体边盲连、慢路径无质量过滤。新版全部修复。
