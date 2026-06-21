# MAGMA × Obsidian 记忆引擎

> **四维记忆引擎联合知识库，为 AI Agent 构建可审查的持久记忆系统**

[English](README.md) | [论文文档](docs/paper/architecture.md) | [API](docs/api.md)

AI Agent 不应该是健忘症。**MAGMA** 将对话经验存入四张正交关系图，**Obsidian** 提供人类审查、接地、可视化的知识工作流。clone 后一条 `docker compose up` 即可运行，MCP 接入你正在用的 Agent。

## 架构

MAGMA 基于 [arXiv 2601.03236](https://arxiv.org/abs/2601.03236) 论文，是与纯向量 RAG 完全不同的多图记忆架构：

```
┌─────────────────────────────────────┐
│  查询：四阶段检索                    │
│  意图→RRF融合→Beam Search→线性化    │
├─────────────────────────────────────┤
│  四图存储                           │
│  语义│时序│因果│实体                  │
│  VectorDB + GraphDB                 │
├─────────────────────────────────────┤
│  记忆演化                           │
│  快路径(写入) + 慢路径(LLM推断)      │
└─────────────────────────────────────┘
```

### 与传统 RAG 的差异

| 维度 | RAG（纯向量） | MAGMA |
|------|-------------|-------|
| **存储** | 扁平文本块 | 四张关系图 |
| **检索** | cos(v_q, v_doc) | RRF 多信号融合 + 图遍历 |
| **关系** | 无 | 时序/因果/语义/实体 |
| **整合** | 无 | LLM 慢路径推断结构 |
| **人审** | 无 | Obsidian 审查/编辑 |

## 快速开始

```bash
git clone https://github.com/your-org/magma-obsidian-memory.git
cd magma-obsidian-memory
cp .env.example .env
# 编辑 .env 填入 LLM API key

docker compose up
# API: http://localhost:8765
# 健康检查: http://localhost:8765/health
```

### 不用 Docker

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8765
```

### 跑测试

```bash
python test_api.py
# 8 项测试：健康检查 → 写事件 → 查询 → 语义边 → 统计 → 持久化
```

## 接入你的 Agent

### Hermes Agent

在 `~/.hermes/config.yaml` 中添加：

```yaml
mcp_servers:
  magma:
    command: "python"
    args: ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]
    timeout: 60
```

然后 `hermes mcp reload`，工具会以 `magma_add_event`、`magma_query` 等形式出现。

### 任意 MCP 客户端

MAGMA 暴露标准 MCP stdio 协议。详见 [integrations/hermes/](integrations/hermes/)。

## Obsidian 集成（可选）

在 `.env` 中配置 vault 路径：

```env
OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault
```

四合一脚本：

| 脚本 | 用途 |
|------|------|
| `obsidian-integration/scripts/dashboard.py` | 实时 MAGMA 统计 → Obsidian 页面 |
| `obsidian-integration/scripts/ingest.py` | Wiki 页面 → MAGMA 实体节点 |
| `obsidian-integration/scripts/review.py` | LLM 推断的边 → 人工审查笔记 |
| `obsidian-integration/scripts/export.py` | MAGMA 图谱 → Obsidian wikilinks + Graph View |

详见 [obsidian-integration/HOWTO.md](obsidian-integration/HOWTO.md)。

## 论文文档

MAGMA 的实现与原论文逐行对齐：

- **[architecture.md](docs/paper/architecture.md)** — 系统架构 + 中文注释
- **[formula-mapping.md](docs/paper/formula-mapping.md)** — 每个公式 → 代码位置
- **[algorithms.md](docs/paper/algorithms.md)** — 三组算法中文注释

## API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/events` | 写入事件（快路径） |
| `POST` | `/events/segmented` | 长文本自动分段批量写入 |
| `GET` | `/events` | 列出事件（分页） |
| `GET` | `/events/{id}` | 获取单个事件 |
| `POST` | `/events/{id}/infer` | 触发慢路径推断 |
| `POST` | `/query` | 四阶段查询 |
| `POST` | `/events/semantic-edges` | 构建语义边 |
| `GET` | `/stats` | 引擎统计 |
| `POST` | `/save` | 持久化到 JSON |
| `POST` | `/load` | 从 JSON 加载 |

## MCP 工具

| 工具 | 说明 |
|------|------|
| `magma_add_event` | 写入事件到记忆 |
| `magma_query` | 四阶段检索 |
| `magma_stats` | 记忆统计 |
| `magma_build_semantic_edges` | 构建语义相似边 |
| `magma_get_recent` | 获取最近事件 |

## 配置

全部通过 `.env` 配置：

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_API_KEY` | 慢路径需要 | — | LLM API key（OpenAI 兼容） |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com` | LLM API 地址 |
| `LLM_MODEL` | 否 | `deepseek-chat` | 模型名 |
| `OBSIDIAN_VAULT_PATH` | 否 | — | Obsidian vault 路径 |
| `HF_HUB_OFFLINE` | 否 | `0` | 设为 `1` 如果 HF 不可达 |

## 项目结构

```
magma-obsidian-memory/
├── README.md / README.zh-CN.md
├── .env.example
├── docker-compose.yml / Dockerfile
├── requirements.txt
├── app.py                    # FastAPI (:8765)
├── mcp_magma_server.py       # MCP stdio 服务
├── test_api.py               # 集成测试
├── memory/                   # 核心引擎
│   ├── graph_db.py           # 四图存储
│   ├── vector_db.py          # 向量索引
│   ├── trg_memory.py         # 快/慢路径引擎
│   └── query_engine.py       # 四阶段检索
├── docs/paper/               # 论文文档
├── obsidian-integration/     # Obsidian 桥接
└── integrations/hermes/      # Hermes MCP 配置
```

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
