"""
MAGMA 四维记忆 — FastAPI 接口

M3: API 层封装，提供 HTTP REST 接口访问 TRGMemory。

启动: uvicorn app:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from memory.trg_memory import TRGMemory
from memory.query_engine import QueryEngine

# 使用绝对路径确保后台进程能找到 .env
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)
logger = logging.getLogger(__name__)

# ── 全局单例 ────────────────────────────────────────────────────

memory = TRGMemory()
query_engine = QueryEngine(memory)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(
    title="MAGMA Memory API",
    version="0.1.0",
    description="Temporal Resonance Graph Memory — 四维记忆架构",
)


@app.on_event("startup")
async def startup():
    """论文 Algorithm 3: 启动慢路径后台 Worker + 预热 encoder"""
    memory.warmup()
    memory.start_consolidation_worker()
    logger.info("MAGMA consolidation worker started")


@app.on_event("shutdown")
async def shutdown():
    memory.stop_consolidation_worker()
    logger.info("MAGMA consolidation worker stopped")


# ── Pydantic 模型 ────────────────────────────────────────────────

class EventCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, description="事件内容")
    timestamp: Optional[str] = Field(None, description="ISO 格式时间，默认当前时间")
    session_id: Optional[str] = Field(None, description="来源会话 ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="附加属性")


class EventResponse(BaseModel):
    node_id: str
    content: str
    timestamp: str
    node_type: str
    session_id: Optional[str] = None
    attributes: Dict[str, Any] = {}


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="查询文本")
    top_k: int = Field(5, ge=1, le=20, description="锚点数量")
    beam_width: int = Field(3, ge=1, le=10, description="Beam Search 宽度")
    max_depth: int = Field(3, ge=1, le=6, description="搜索深度")
    budget: int = Field(30, ge=1, le=100, description="最大检索节点数")
    max_tokens: int = Field(3000, ge=100, le=10000, description="线性化输出 token 上限")


class QueryResponse(BaseModel):
    intent: str
    anchors: int
    retrieved_nodes: int
    context: str
    statistics: Dict[str, Any]


class StatsResponse(BaseModel):
    events_added: int
    links_created: int
    queries_processed: int
    nodes: int
    edges: int
    vectors: int


class SemanticEdgeRequest(BaseModel):
    threshold: float = Field(0.7, ge=0.0, le=1.0, description="余弦相似度阈值")


# ── API 端点 ────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "magma-memory"}


@app.post("/events", response_model=EventResponse, status_code=201)
async def create_event(req: EventCreateRequest):
    """
    写入一个事件（快路径）。

    1. 创建 EventNode
    2. 编码 embedding
    3. 存图 + 向量库
    4. 自动加时间边 + 入队触发慢路径
    """
    ts = datetime.fromisoformat(req.timestamp) if req.timestamp else None
    node_id = memory.add_event(
        content=req.content,
        timestamp=ts,
        session_id=req.session_id,
        metadata=req.metadata,
    )
    node = memory.get_node(node_id)
    if not node:
        raise HTTPException(500, "Failed to create event node")
    return EventResponse(
        node_id=node.node_id,
        content=node.content_narrative,
        timestamp=node.timestamp.isoformat() if node.timestamp else "",
        node_type=node.node_type.value,
        session_id=node.session_id,
        attributes=node.attributes,
    )


@app.post("/events/segmented", status_code=201)
async def create_events_segmented(req: EventCreateRequest):
    """
    G6: 将长文本按句末标点自动分段 → 批量写入离散事件。

    返回所有创建的事件节点 ID 列表。
    """
    ts = datetime.fromisoformat(req.timestamp) if req.timestamp else None
    node_ids = memory.add_events_segmented(
        content=req.content,
        timestamp=ts,
        session_id=req.session_id,
        metadata=req.metadata,
    )
    return {"node_ids": node_ids, "count": len(node_ids)}


@app.get("/events/{node_id}", response_model=EventResponse)
async def get_event(node_id: str):
    """获取某个事件的详细信息"""
    node = memory.get_node(node_id)
    if not node:
        raise HTTPException(404, f"Event {node_id} not found")
    return EventResponse(
        node_id=node.node_id,
        content=node.content_narrative,
        timestamp=node.timestamp.isoformat() if node.timestamp else "",
        node_type=node.node_type.value,
        session_id=node.session_id,
        attributes=node.attributes,
    )


@app.get("/events", response_model=List[EventResponse])
async def list_events(limit: int = 20, offset: int = 0):
    """列出所有事件（支持分页）"""
    nodes = memory.graph_db.get_event_nodes()
    nodes.sort(key=lambda n: n.timestamp or datetime.min, reverse=True)
    page = nodes[offset:offset + limit]
    return [
        EventResponse(
            node_id=n.node_id,
            content=n.content_narrative,
            timestamp=n.timestamp.isoformat() if n.timestamp else "",
            node_type=n.node_type.value,
            session_id=n.session_id,
            attributes=n.attributes,
        )
        for n in page
    ]


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    完整 4 阶段查询：

    1. Intent Classification → WHY / WHEN / WHAT / ENTITY
    2. RRF 锚点定位（向量 + 关键词融合）
    3. Adaptive Beam Search 图遍历
    4. Narrative Synthesis 线性化输出
    """
    result = query_engine.query(
        query_text=req.query,
        top_k=req.top_k,
        beam_width=req.beam_width,
        max_depth=req.max_depth,
        budget=req.budget,
        max_tokens=req.max_tokens,
    )
    return QueryResponse(**result)


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """记忆引擎统计信息"""
    s = memory.get_stats()
    return StatsResponse(**s)


@app.post("/events/semantic-edges")
async def build_semantic_edges(req: SemanticEdgeRequest):
    """
    在事件节点间构建语义边（cosine > threshold）。
    """
    count = memory.build_semantic_edges(threshold=req.threshold)
    return {"semantic_edges_created": count, "threshold": req.threshold}


@app.post("/events/{node_id}/infer")
async def infer_edges(node_id: str):
    """慢路径：用 LLM 推断某个节点的因果/实体边（2-hop 子图）。"""
    if not memory.get_node(node_id):
        raise HTTPException(404, f"Event {node_id} not found")
    result = memory.infer_causal_and_entity_edges(node_id)
    return {"node_id": node_id, **result}


@app.get("/debug/llm")
async def debug_llm():
    """调试：测试 LLM 连接和 API key 是否正常"""
    try:
        llm = memory._get_llm()
        import os
        key_ok = bool(os.getenv("DEEPSEEK_API_KEY"))
        resp = llm.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )
        return {"llm_ok": True, "key_loaded": key_ok, "response": resp.choices[0].message.content}
    except Exception as e:
        return {"llm_ok": False, "error": str(e), "key_loaded": bool(os.getenv("DEEPSEEK_API_KEY"))}


@app.post("/save")
async def save_memory(filename: str = "magma_memory.json"):
    """持久化记忆到文件。"""
    path = os.path.join(DATA_DIR, filename)
    memory.save_to_file(path)
    return {"saved": True, "path": path, "nodes": memory.graph_db.node_count()}


@app.post("/load")
async def load_memory(filename: str = "magma_memory.json"):
    """从文件加载记忆。"""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, f"File not found: {path}")
    memory.load_from_file(path)
    return {
        "loaded": True,
        "path": path,
        "nodes": memory.graph_db.node_count(),
        "edges": memory.graph_db.edge_count(),
    }
