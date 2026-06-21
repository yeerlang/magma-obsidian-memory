<p align="center">
  <img src="assets/banner-zh.svg" alt="MAGMA × Obsidian" width="100%">
</p>

<p align="center">
  <a href="https://github.com/yeerlang/magma-obsidian-memory/blob/master/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://arxiv.org/abs/2601.03236"><img src="https://img.shields.io/badge/Paper-arXiv%202601.03236-B31B1B.svg" alt="arXiv"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/English-README-blue.svg" alt="English"></a>
  <a href="https://github.com/yeerlang/magma-obsidian-memory"><img src="https://img.shields.io/badge/MCP-Compatible-7c3aed.svg" alt="MCP Compatible"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-stdio-FF6B6B.svg" alt="MCP stdio"></a>
</p>

# MAGMA × Obsidian 记忆引擎

> 你的 Agent 每次会话结束就失忆。修好它。

[English](README.en.md) | [论文文档](docs/paper/architecture.md) | [API](docs/api.md)

|**MAGMA 给你的 AI Agent 装上四维记忆，通过 Obsidian 实现人可审计的知识演化。** MAGMA 全称 **M**ulti-**G**raph based **A**gentic **M**emory **A**rchitecture（多图基智能体记忆架构）—— 不是向量搜索那种"把文本块甩给每次查询"的扁平匹配——MAGMA 把经验存进四张互联的关系图（时序、因果、语义、实体），检索时走的是*关系遍历*而非向量相似度。

|**Obsidian 是 MAGMA 的人机协作界面。** LLM 慢路径推断的每条因果边、实体关系都会进入 Obsidian 审查队列——你可以逐条确认、修正或驳回。MAGMA 图谱可导出为 Obsidian Graph View 可视化，Wiki 页面与实体节点双向同步。Agent 的记忆不再是不透明的黑箱，而是你可以随时翻阅、编辑的知识库。|

|基于 [MAGMA 论文](https://arxiv.org/abs/2601.03236) (arXiv 2601.03236)，一条 `docker compose up` 启动，MCP 协议直连 Hermes、Claude、Cursor、Cline、Windsurf、Continue 等所有主流 Agent。

|**你的 Agent，你的数据，你的规则。** 嵌入向量本地生成，LLM 调用按需配置，无锁定，无黑箱。

## MAGMA 的差异优势

| | 纯 RAG | LangChain Memory | Mem0 | **MAGMA** |
|---|---|---|---|---|
| **存储** | 扁平文本块 | 键值存储 | 扁平事件 | **四张关系图** |
| **检索** | cos(v_q, v_doc) | 最近 N 条消息 | cos 相似度 | **RRF 多信号融合 + 图遍历** |
| **关系** | 无 | 仅时序 | 无 | **时序/因果/语义/实体** |
| **整合** | 无 | 无 | 无 | **LLM 慢路径推断结构** |
| **人审** | 无 | 无 | 无 | **Obsidian 审查/编辑** |
| **MCP 原生** | ❌ | ❌ | ❌ | **✅ stdio 服务** |

## Obsidian 审查工作流

MAGMA 区别于所有纯向量记忆方案的核心：**慢路径推理结果必须经过人工审查才固化入图**，而 Obsidian 是唯一的人机审查界面。

```
事件写入 ──→ 快路径 ──→ 存入图谱（时序/语义边自动创建）
                │
                ▼
          慢路径后台队列
                │
                ▼
         LLM 推断因果/实体关系
                │
                ▼
    ┌── Obsidian 审查队列 ──┐
    │  逐条展示推断结果       │
    │  ✅ 确认 → 固化入图     │
    │  ✏️ 修正 → 重新写入     │
    │  ❌ 驳回 → 丢弃        │
    └──────────────────────┘
                │
                ▼
    Obsidian Graph View 可视化
```

| 审查维度 | 说明 |
|----------|------|
| **因果边** | LLM 推断的 LEADS_TO / BECAUSE_OF / ENABLES / PREVENTS 关系 → 人工确认后生效 |
| **实体边** | LLM 提取的 REFERS_TO / MENTIONED_IN 关联 → 人工修正实体名和关系 |
| **语义边** | 自动创建（cos 相似度 > 阈值），可在 Obsidian 中查看和删除 |
| **图谱导出** | 完整 MAGMA 图谱 → Obsidian wikilinks + Graph View 交互式浏览 |

> **为什么必须有 Obsidian？** 没有审查的 AI 记忆 = 幻觉永久化。Mem0、LangChain Memory 的 LLM 推断结果直接入库，错了就永远错了。MAGMA 的 Obsidian 审查队列确保你的知识库永远是经过人工验证的。

## 架构

MAGMA 基于 [arXiv 2601.03236](https://arxiv.org/abs/2601.03236) 论文，是与纯向量 RAG 完全不同的多图记忆架构：

<p align="center">
  <img src="assets/magma-architecture.png" alt="MAGMA 三层架构图" width="100%">
</p>

> **三层设计**：上层 **查询流程** — 意图分类 → RRF 多信号融合 → Beam Search 图遍历 → 线性化输出。中层 **数据结构** — GraphDB 存储四类边（时序/因果/语义/实体），VectorDB 索引嵌入向量。底层 **记忆演化** — 快路径即时写入事件；慢路径后台用 LLM 推断因果与实体结构。

### 四阶段查询流水线

<p align="center">
  <img src="assets/query-pipeline.png" alt="查询流水线" width="100%">
</p>

> **(1) 意图分类** 识别 WHY/WHEN/WHAT/ENTITY → **(2) RRF 多信号融合** 合并向量 + 关键词 + 时间过滤 → **(3) Beam Search** 按意图加权边优先级遍历图谱 → **(4) 线性化** 拓扑排序 + token 预算截断。

## 为什么选择 MAGMA？

**"幻觉不会累积吗？"** — 每条边都标注了来源。Obsidian 集成让你在 LLM 推断的关系固化前审查修正。因果边经过人工确认审查队列。

**"事件超过 1000 条会崩吗？"** — Beam Search 带预算控制（`budget=30`），检索开销不随图规模线性增长。RRF 融合确保信噪比不退化。

**"需要 API key 吗？"** — 快路径（写入 + 查询）完全离线，使用本地 embedding。只有慢路径（因果/实体推断）需要 LLM。任意 OpenAI 兼容端点均可。

**"这跟向量数据库有什么区别？"** — 本质不同。向量搜索只是 RRF 三条信号源之一（另两条：关键词匹配、时间过滤）。图遍历步骤（意图加权的 Beam Search）才是让检索从"扁平匹配"变为"关系推理"的关键。

## 快速开始

```bash
git clone https://github.com/yeerlang/magma-obsidian-memory.git
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

MAGMA 使用标准 MCP stdio 协议，兼容所有支持 MCP 的 AI Agent。

### Hermes Agent

在 `~/.hermes/config.yaml` 中添加：

```yaml
mcp_servers:
  magma:
    command: "python"
    args: ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]
    timeout: 60
```

`hermes mcp reload`，工具以 `magma_add_event`、`magma_query` 等形式出现。

### Claude Desktop / Claude Code

`~/.config/claude/claude_desktop_config.json`：

```json
{"mcpServers": {"magma": {"command": "python", "args": ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]}}}
```

### Cursor

项目根目录 `.cursor/mcp.json`：

```json
{"mcpServers": {"magma": {"command": "python", "args": ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]}}}
```

### Cline（VS Code）

Cline 设置 → MCP Servers → 添加：

```json
{"mcpServers": {"magma": {"command": "python", "args": ["/path/to/magma-obsidian-memory/mcp_magma_server.py"], "disabled": false, "alwaysAllow": ["magma_add_event", "magma_query", "magma_stats"]}}}
```

### Windsurf

`.windsurf/mcp.json`：

```json
{"mcpServers": {"magma": {"command": "python", "args": ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]}}}
```

### Continue（VS Code / JetBrains）

`~/.continue/config.json`：

```json
{"experimental": {"mcpServers": {"magma": {"command": "python", "args": ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]}}}}
```

### OpenCode / Codex / Aider / Goose

均支持 MCP stdio。在上述工具的 MCP 配置中使用相同格式：`{"command": "python", "args": ["/path/to/mcp_magma_server.py"]}`。

### 任意 Agent（REST API）

不支持 MCP 的 Agent 可直接调 REST API：

```python
import requests
r = requests.post("http://localhost:8765/events", json={"content": "用户偏好深色主题"})
r = requests.post("http://localhost:8765/query", json={"query": "深色主题"})
```

完整 API 文档：[docs/api.md](docs/api.md)

## Obsidian 集成脚本

在 `.env` 中配置你的 Obsidian Vault 路径即可启用审查工作流：

```env
OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault
```

四合一运维脚本：

| 脚本 | 用途 |
|------|------|
| `obsidian-integration/scripts/dashboard.py` | 实时 MAGMA 统计 → Obsidian 页面 |
| `obsidian-integration/scripts/ingest.py` | Wiki 页面 → MAGMA 实体节点 |
| `obsidian-integration/scripts/review.py` | LLM 推断的边 → 人工审查笔记 |
| `obsidian-integration/scripts/export.py` | MAGMA 图谱 → Obsidian wikilinks + Graph View |

详见 [obsidian-integration/HOWTO.md](obsidian-integration/HOWTO.md)。

## 隐私与数据流

MAGMA 默认本地处理你的数据：

- **嵌入向量**：本地生成，使用 `sentence-transformers`（all-MiniLM-L6-v2），绝不外传。
- **图存储**：内存中（GraphDB + VectorDB），可通过 `POST /save` 持久化为 JSON。
- **LLM 调用**：仅慢路径（因果/实体推断）调用你配置的 LLM。快路径和查询完全本地。
- **API Key**：存储于本地 `.env`，不会被记录或传输。
- **Obsidian vault**：只读你配置的 `OBSIDIAN_VAULT_PATH`，仅在 `magma/` 子目录下写入。

当不配置 LLM 时，MAGMA 完全离线运行——写入事件、搜索向量、遍历图谱，全部本地。

## 论文文档

MAGMA 的实现与原论文逐行对齐：

| 文档 | 内容 |
|------|------|
| **[architecture.md](docs/paper/architecture.md)** | 系统架构 + 中文注释 + 原图 |
| **[formula-mapping.md](docs/paper/formula-mapping.md)** | 每个公式 → 代码位置 |
| **[algorithms.md](docs/paper/algorithms.md)** | 三组算法中文注释 |
| **[paper.pdf](docs/paper/paper.pdf)** | 完整论文 (arXiv 2601.03236) |

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

## 参与贡献

```bash
git clone https://github.com/yeerlang/magma-obsidian-memory.git
cd magma-obsidian-memory
pip install -r requirements.txt

# 跑测试
python test_api.py

# 启动开发服务器
python -m uvicorn app:app --host 0.0.0.0 --port 8765 --reload
```

欢迎提 PR。待办任务见 [issues](https://github.com/yeerlang/magma-obsidian-memory/issues)。

## 项目结构

```
magma-obsidian-memory/
├── README.md / README.zh-CN.md
├── .env.example / .gitignore / LICENSE
├── docker-compose.yml / Dockerfile
├── requirements.txt
├── assets/                   # Banner + 品牌素材
├── app.py                    # FastAPI (:8765)
├── mcp_magma_server.py       # MCP stdio 服务
├── test_api.py               # 集成测试
├── memory/                   # 核心引擎
│   ├── graph_db.py           # 四图存储
│   ├── vector_db.py          # 向量索引
│   ├── trg_memory.py         # 快/慢路径引擎
│   └── query_engine.py       # 四阶段检索
├── docs/
│   ├── api.md / setup.md
│   └── paper/                # 论文文档 + 原图
├── obsidian-integration/     # Obsidian 桥接
└── integrations/hermes/      # Hermes MCP 配置
```

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=yeerlang/magma-obsidian-memory&type=Date)](https://star-history.com/#yeerlang/magma-obsidian-memory&Date)

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
