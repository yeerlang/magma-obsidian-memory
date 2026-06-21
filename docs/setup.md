# MAGMA 部署指南

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|:------:|------|
| Python | 3.10+ | 3.11+ 推荐 |
| Docker | 20.10+ | 可选，推荐 |
| 内存 | 1GB | 含模型缓存 |
| 磁盘 | 2GB | 含模型和依赖 |

## 方式一：Docker（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/magma-obsidian-memory.git
cd magma-obsidian-memory

# 2. 配置环境
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 3. 启动
docker compose up -d

# 4. 验证
curl http://localhost:8765/health
# → {"status": "ok", "service": "magma-memory"}
```

## 方式二：手动部署

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/magma-obsidian-memory.git
cd magma-obsidian-memory

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY

# 5. 预下载模型（可选，加速首次启动）
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# 6. 启动
python -m uvicorn app:app --host 0.0.0.0 --port 8765

# 7. 验证
curl http://localhost:8765/health
```

## 配置说明

编辑 `.env`：

```bash
# 必需：LLM API key（慢路径需要）
LLM_API_KEY=sk-your-api-key-here

# LLM 后端（默认 DeepSeek，可用任意 OpenAI 兼容 API）
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# Obsidian 集成（可选）
OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault

# HuggingFace 离线模式（HF 不可达时设为 1）
HF_HUB_OFFLINE=0
```

## 防火墙注意事项

### 中国环境

- HuggingFace 被墙 → 设置 `HF_HUB_OFFLINE=1`，手动预下载模型
- DeepSeek API 可直连 → 默认配置无需代理

### Docker 环境

Docker 内 `HF_HUB_OFFLINE=1` 默认关闭。若需离线，在 `docker-compose.yml` 中设置环境变量，或 build 时预下载模型。

## 验证部署

```bash
# 完整集成测试
python test_api.py
```

预期输出：

```
[200] GET /health  {"status":"ok","service":"magma-memory"}
[201] POST /events  {"node_id":"xxx-xxx","content":"...","...","node_type":"EVENT"}
[201] POST /events  ...
[201] POST /events  ...
[200] GET /events?limit=10  [...]
[200] GET /events/xxx  ...
[200] POST /query  {"intent":"WHAT","anchors":3,...}
[200] POST /events/semantic-edges  {"semantic_edges_created":...}
[200] GET /stats  {"events_added":5,...}
[200] POST /save  {"saved":true,...}
Done.
```

## 常见问题

### 启动后 health 返回 Connection Refused

模型首次加载需要 5-30 秒。Docker build 时已预下载，手动部署首次启动需等待。

### Slow Path 返回 0/0

检查 LLM API key 是否正确：`curl http://localhost:8765/debug/llm`

### 中文查询无时间窗口

G4 时间解析器仅支持 12 种中文表达式（昨天/今天/上周/本月等）。复杂表达式返回 None（不报错，仅跳过时间过滤）。
