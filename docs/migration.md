## 升级指南（从旧版本迁移）

如果你之前部署了 MAGMA（commit 早于 2026-07-01），请按以下步骤升级：

### 1. 拉取最新代码

```bash
git pull origin master
```

### 2. 清理存量冗余边

旧版 `build_semantic_edges()` 无去重，可能已累积数千条重复边：

```bash
python obsidian-integration/scripts/cleanup-edges.py --min-weight 0.6
# 输出: 去重移除 X 条边 → 边/节点比应 <10x
```

脚本自动备份原文件为 `.json.bak`，可随时回滚。

### 3. 重启服务

新代码修复了 VectorDB 持久化——重启后 `/stats` 中 `vectors` 不再为 0：

```bash
# 停止旧进程，重新启动
python -m uvicorn app:app --host 0.0.0.0 --port 8765
```

### 4. 验证修复

```bash
curl http://localhost:8765/stats
# vectors 应 > 0（旧版重启后为 0）
# edges/nodes 应 < 10（旧版可能数百倍）
```

### 5. （可选）注册定时任务

建议定期清理边防止再次膨胀（cron 每 6-12 小时）：

```bash
0 */6 * * * cd /path/to/magma && python obsidian-integration/scripts/cleanup-edges.py --min-weight 0.6
```

### 已修复的问题

| Bug | 症状 | 修复 |
|-----|------|------|
| VectorDB 不持久化 | 重启后 vectors=0，语义搜索失效 | `load_from_file()` 重建索引 |
| 边爆炸 | 边/节点比数百倍，查询降级 | O(1)去重 + 智能采样 + max_edges |
| 实体边盲连 | 实体连到不相关的事件 | name-in-content 过滤 |
| 慢路径质量 | LLM 输出全收，低质量边污染图谱 | confidence≥70 门槛 |
| 端口不一致 | 摄入脚本连接失败 | 默认端口统一 |
