# MAGMA API 参考

> FastAPI REST API (:8765) + MCP 工具

## REST API

### 健康检查

```http
GET /health
```

响应：
```json
{"status": "ok", "service": "magma-memory"}
```

---

### 写入事件（快路径）

```http
POST /events
Content-Type: application/json

{
  "content": "事件文本内容",
  "timestamp": "2026-06-21T10:00:00",     // 可选
  "session_id": "session-abc",             // 可选
  "metadata": {"key": "value"}             // 可选
}
```

响应 (201)：
```json
{
  "node_id": "uuid",
  "content": "事件文本内容",
  "timestamp": "2026-06-21T10:00:00",
  "node_type": "EVENT",
  "session_id": "session-abc",
  "attributes": {"key": "value"}
}
```

---

### 分段批量写入 [G6]

```http
POST /events/segmented
Content-Type: application/json

{
  "content": "长文本。会被自动按句末标点分段。每段成为一个独立事件。",
  "session_id": "session-abc"
}
```

响应 (201)：
```json
{
  "node_ids": ["uuid1", "uuid2", "uuid3"],
  "count": 3
}
```

分段规则：按 `。！？\n` 切分，忽略空段和过短段（<5字符）。

---

### 获取单个事件

```http
GET /events/{node_id}
```

响应 (200)：同 `EventResponse` 模型。

---

### 列出事件（分页）

```http
GET /events?limit=20&offset=0
```

响应 (200)：
```json
[{"node_id": "...", "content": "...", ...}, ...]
```

---

### 四阶段查询

```http
POST /query
Content-Type: application/json

{
  "query": "sentence-transformers 下载",
  "top_k": 5,
  "beam_width": 3,
  "max_depth": 3,
  "budget": 30,
  "max_tokens": 3000
}
```

响应 (200)：
```json
{
  "intent": "WHAT",
  "anchors": 5,
  "retrieved_nodes": 12,
  "context": "<t:2026-06-21 10:00> ...\n<t:2026-06-21 09:30> ...",
  "statistics": {
    "query": "sentence-transformers 下载",
    "time_window": "2026-06-20T00:00:00/2026-06-21T23:59:59",
    "nodes_in_graph": 150,
    "edges_in_graph": 320
  }
}
```

---

### 构建语义边

```http
POST /events/semantic-edges
Content-Type: application/json

{"threshold": 0.7}
```

响应 (200)：
```json
{"semantic_edges_created": 15, "threshold": 0.7}
```

---

### 慢路径推断（按需）

```http
POST /events/{node_id}/infer
```

响应 (200)：
```json
{"node_id": "uuid", "causal": 2, "entity": 1}
```

**注意**：此端点同步调用 LLM（5-60 秒），会阻塞单 worker 服务器的其他请求。

---

### 统计

```http
GET /stats
```

响应 (200)：
```json
{
  "events_added": 120,
  "links_created": 85,
  "queries_processed": 30,
  "nodes": 120,
  "edges": 85,
  "vectors": 120
}
```

---

### 持久化

```http
POST /save?filename=magma_memory.json
```

响应 (200)：
```json
{"saved": true, "path": "data/magma_memory.json", "nodes": 120}
```

---

### 加载

```http
POST /load?filename=magma_memory.json
```

响应 (200)：
```json
{"loaded": true, "path": "data/magma_memory.json", "nodes": 120, "edges": 85}
```

---

### LLM 调试

```http
GET /debug/llm
```

响应 (200)：
```json
{"llm_ok": true, "key_loaded": true, "response": "OK"}
```

---

## MCP 工具

MAGMA 暴露 5 个 MCP 工具（通过 stdio）：

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `magma_add_event` | `content` (required), `session_id`, `metadata` | 写入一个事件 |
| `magma_query` | `query` (required), `top_k` (default: 5) | 四阶段查询 |
| `magma_stats` | — | 记忆统计 |
| `magma_build_semantic_edges` | `threshold` (default: 0.3) | 构建语义相似边 |
| `magma_get_recent` | `limit` (default: 10) | 获取最近事件 |

### Hermes 配置示例

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  magma:
    command: "python"
    args: ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]
    timeout: 60
```

配置后执行 `hermes mcp reload`，工具即可用。
