"""
MAGMA MCP Server — 让 Hermes 通过 MCP 协议调用 MAGMA 记忆系统

启动方式（手动测试）:
  python mcp_magma_server.py

Hermes 配置（~/.hermes/config.yaml）:
  mcp_servers:
    magma:
      command: "python"
      args: ["/path/to/magma-obsidian-memory/mcp_magma_server.py"]
      timeout: 60

需安装: pip install mcp
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

# 添加项目根目录到路径
MAGMA_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, MAGMA_DIR)

# ── 初始化 MAGMA 引擎（全局单例） ──────────────────────────────

from memory.trg_memory import TRGMemory
from memory.query_engine import QueryEngine

memory = TRGMemory()
query_engine = QueryEngine(memory)

logger = logging.getLogger(__name__)


# ── Tool handlers ─────────────────────────────────────────────────

def handle_add_event(content: str, session_id: str = "", metadata: str = "") -> str:
    """写入一个事件到 MAGMA 记忆"""
    meta = json.loads(metadata) if metadata else {}
    node_id = memory.add_event(
        content=content,
        session_id=session_id or None,
        metadata=meta,
    )
    return json.dumps({"node_id": node_id, "status": "created"})


def handle_query(query: str, top_k: int = 5) -> str:
    """查询 MAGMA 记忆"""
    result = query_engine.query(
        query_text=query,
        top_k=top_k,
        beam_width=3,
        max_depth=3,
        budget=30,
    )
    return json.dumps(result, ensure_ascii=False)


def handle_stats() -> str:
    """获取记忆引擎统计"""
    s = memory.get_stats()
    return json.dumps(s)


def handle_build_semantic_edges(threshold: float = 0.3) -> str:
    """构建语义边"""
    count = memory.build_semantic_edges(threshold=threshold)
    return json.dumps({"semantic_edges_created": count})


def handle_save(filename: str = "magma_memory.json") -> str:
    """持久化记忆"""
    path = os.path.join(MAGMA_DIR, "data", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    memory.save_to_file(path)
    return json.dumps({"saved": True, "path": path})


def handle_get_recent(limit: int = 10) -> str:
    """获取最近的事件"""
    nodes = memory.graph_db.get_event_nodes()
    nodes.sort(key=lambda n: n.timestamp or datetime.min, reverse=True)
    results = []
    for n in nodes[:limit]:
        results.append({
            "node_id": n.node_id,
            "content": n.content_narrative[:200],
            "timestamp": n.timestamp.isoformat() if n.timestamp else "",
            "session_id": n.session_id,
        })
    return json.dumps(results, ensure_ascii=False)


# ── Tool schemas ──────────────────────────────────────────────────

TOOLS = [
    {
        "name": "magma_add_event",
        "description": "Write an event to MAGMA memory. Content is automatically embedded and stored in the graph+vector databases. Use this to save important conversation context, decisions, or facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The event content/text to remember"},
                "session_id": {"type": "string", "description": "Optional session identifier"},
                "metadata": {"type": "string", "description": "Optional JSON string with extra attributes"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "magma_query",
        "description": "Query MAGMA memory using 4-stage retrieval (intent classification → RRF fusion → beam search → linearization). Returns relevant context from past events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query text in natural language"},
                "top_k": {"type": "number", "description": "Number of anchor nodes (default: 5, max: 20)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "magma_stats",
        "description": "Get MAGMA memory statistics: node count, edge count, event count, query count, vector count.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "magma_build_semantic_edges",
        "description": "Build semantic similarity edges between events based on embedding cosine similarity. Run this periodically to connect related memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "description": "Cosine similarity threshold (default: 0.3, range: 0.0-1.0)"},
            },
        },
    },
    {
        "name": "magma_get_recent",
        "description": "Get recent events from MAGMA memory, sorted by time descending.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "number", "description": "Number of recent events to return (default: 10)"},
            },
        },
    },
]

HANDLERS = {
    "magma_add_event": handle_add_event,
    "magma_query": handle_query,
    "magma_stats": handle_stats,
    "magma_build_semantic_edges": handle_build_semantic_edges,
    "magma_get_recent": handle_get_recent,
}


# ── MCP stdio protocol ────────────────────────────────────────────

def handle_request(req: dict) -> dict:
    """Handle a single MCP JSON-RPC request."""
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "magma-memory", "version": "0.1.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # no response

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        tool_name = req.get("params", {}).get("name", "")
        arguments = req.get("params", {}).get("arguments", {})

        handler = HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }

        try:
            result_text = handler(**arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    # Ping
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    """MCP stdio server — reads JSON-RPC from stdin, writes to stdout."""
    # 取消 stdout 缓冲
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    logger.info("MAGMA MCP server starting...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            response = handle_request(req)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            sys.stderr.write(f"Invalid JSON: {line}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    main()
