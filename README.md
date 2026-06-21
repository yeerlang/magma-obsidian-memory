# MAGMA × Obsidian Memory

> **Four-Graph Memory Engine with Human-Curated Knowledge Grounding for AI Agents**

[中文文档](README.zh-CN.md) | [Paper](docs/paper/architecture.md) | [API](docs/api.md)

AI agents shouldn't be amnesiacs. **MAGMA** stores conversational experience across four orthogonal relational graphs. **Obsidian** provides human review, grounding, and visualization workflows. Clone, `docker compose up`, and connect via MCP to the agent you're already using.

## Architecture

MAGMA is based on [arXiv 2601.03236](https://arxiv.org/abs/2601.03236) — a multi-graph agentic memory architecture that diverges from vector-only RAG:

```
┌─────────────────────────────────────┐
│  Query: 4-Stage Retrieval           │
│  Intent → RRF → Beam Search → Line  │
├─────────────────────────────────────┤
│  4-Graph Storage                    │
│  Semantic │ Temporal │ Causal │ Ent │
│  VectorDB + GraphDB                 │
├─────────────────────────────────────┤
│  Memory Evolution                   │
│  Fast Path (write) + Slow Path (LLM)│
└─────────────────────────────────────┘
```

### What makes it different

| | RAG (Vector-only) | MAGMA |
|---|---|---|
| **Storage** | Flat chunks | 4 relational graphs |
| **Retrieval** | cos(v_q, v_doc) | RRF fusion + beam search traversal |
| **Relations** | None | Temporal / Causal / Semantic / Entity |
| **Consolidation** | None | LLM slow path infers structure |
| **Human review** | None | Obsidian vault for audit/edit |

## Quick Start

```bash
git clone https://github.com/your-org/magma-obsidian-memory.git
cd magma-obsidian-memory
cp .env.example .env
# Edit .env with your LLM API key

docker compose up
# API: http://localhost:8765
# Health: http://localhost:8765/health
```

### Without Docker

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8765
```

### Test it

```bash
python test_api.py
# 8 tests: health → write events → query → semantic edges → stats → save
```

## Connect Your Agent

### Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  magma:
    command: "python"
    args: ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]
    timeout: 60
```

Then `hermes mcp reload` — tools appear as `magma_add_event`, `magma_query`, etc.

### Any MCP Client

MAGMA exposes a standard MCP stdio server. See [integrations/hermes/](integrations/hermes/) for details.

## Obsidian Integration (Optional)

Configure your vault path in `.env`:

```env
OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault
```

Four integration scripts:

| Script | Purpose |
|---|---|
| `obsidian-integration/scripts/dashboard.py` | Live MAGMA stats → Obsidian page |
| `obsidian-integration/scripts/ingest.py` | Wiki pages → MAGMA entity nodes |
| `obsidian-integration/scripts/review.py` | LLM-inferred edges → human review notes |
| `obsidian-integration/scripts/export.py` | MAGMA graph → Obsidian wikilinks + Graph View |

See [obsidian-integration/HOWTO.md](obsidian-integration/HOWTO.md) for setup.

## Paper Documentation

MAGMA's implementation is mapped line-by-line to the original paper:

- **[architecture.md](docs/paper/architecture.md)** — System architecture with annotated diagrams
- **[formula-mapping.md](docs/paper/formula-mapping.md)** — Every formula → code location
- **[algorithms.md](docs/paper/algorithms.md)** — All 3 algorithms with Chinese annotations

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/events` | Write event (Fast Path) |
| `POST` | `/events/segmented` | Auto-segment long text → batch write |
| `GET` | `/events` | List events (paginated) |
| `GET` | `/events/{id}` | Get single event |
| `POST` | `/events/{id}/infer` | Trigger Slow Path inference |
| `POST` | `/query` | 4-stage query |
| `POST` | `/events/semantic-edges` | Build semantic similarity edges |
| `GET` | `/stats` | Engine statistics |
| `POST` | `/save` | Persist to JSON |
| `POST` | `/load` | Load from JSON |

## MCP Tools

| Tool | Description |
|---|---|
| `magma_add_event` | Write an event to memory |
| `magma_query` | 4-stage retrieval query |
| `magma_stats` | Memory statistics |
| `magma_build_semantic_edges` | Build semantic similarity edges |
| `magma_get_recent` | Get recent events |

## Configuration

All configuration via `.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_API_KEY` | For Slow Path | — | Your LLM API key (OpenAI-compatible) |
| `LLM_BASE_URL` | No | `https://api.deepseek.com` | LLM API base URL |
| `LLM_MODEL` | No | `deepseek-chat` | Model name |
| `OBSIDIAN_VAULT_PATH` | No | — | Path to Obsidian vault |
| `HF_HUB_OFFLINE` | No | `0` | Set to `1` if HF is unreachable |

## Project Structure

```
magma-obsidian-memory/
├── README.md / README.zh-CN.md
├── .env.example
├── docker-compose.yml / Dockerfile
├── requirements.txt
├── app.py                    # FastAPI (:8765)
├── mcp_magma_server.py       # MCP stdio server
├── test_api.py               # Integration tests
├── memory/                   # Core engine
│   ├── graph_db.py           # 4-graph storage
│   ├── vector_db.py          # Vector index
│   ├── trg_memory.py         # Fast/Slow path engine
│   └── query_engine.py       # 4-stage retrieval
├── docs/paper/               # Paper documentation
├── obsidian-integration/     # Obsidian bridge
└── integrations/hermes/      # Hermes MCP config
```

## License

MIT — see [LICENSE](LICENSE).
