---
name: magma-memory
description: "MAGMA (Multi-Graph Agentic Memory Architecture) — build and operate a 4-graph memory engine for AI agents. Based on arxiv 2601.03236."
version: 1.0.0
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [memory, graph, agent, retrieval, rag-alternative]
    category: mlops
---

# MAGMA — Multi-Graph Agentic Memory Architecture

Build, operate, and extend a 4-graph memory engine based on the MAGMA paper
(arxiv 2601.03236). MAGMA stores agent experience across four orthogonal
relational graphs (Semantic, Temporal, Causal, Entity) and retrieves via
policy-guided graph traversal.

## Quick Start

```bash
# Clone and start
cd magma-obsidian-memory
cp .env.example .env  # edit with your LLM API key
docker compose up

# Or without Docker
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8765
```

## Hermes Integration

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  magma:
    command: "python"
    args: ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]
    timeout: 60
```

Then `hermes mcp reload`. Tools appear as:
- `magma_add_event` — Write events to memory
- `magma_query` — 4-stage retrieval query
- `magma_stats` — Memory statistics
- `magma_build_semantic_edges` — Build semantic similarity edges
- `magma_get_recent` — Get recent events

## Architecture

```
Query: Intent -> RRF -> Beam Search -> Linearize
Storage: Semantic | Temporal | Causal | Entity (GraphDB + VectorDB)
Evolution: Fast Path (write) + Slow Path (LLM inference)
```

## Paper Alignment

All 6 paper gaps resolved. See `docs/paper/` for:
- Architecture diagrams with Chinese annotations
- Formula → code line-by-line mapping
- Algorithm pseudocode with commentary

## Configuration

| Variable | Required | Description |
|---|---|---|
| `LLM_API_KEY` | Slow Path | Your LLM API key |
| `LLM_BASE_URL` | No | API base URL (default: deepseek) |
| `LLM_MODEL` | No | Model name (default: deepseek-chat) |
| `OBSIDIAN_VAULT_PATH` | No | Path to Obsidian vault |

## Pitfalls

- **HF_HUB_OFFLINE=1**: Set if HuggingFace is unreachable. Pre-download `all-MiniLM-L6-v2` model.
- **Single worker blocks on Slow Path**: `/events/{id}/infer` makes synchronous LLM calls. Use `--workers 2` if needed.
- **add_event returns `node_id`**, not `id` or `event_id`.
- **First POST blocks server**: The encoder loads on first request. Warm up with `/health` first.
