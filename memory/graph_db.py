"""
Graph Database — 四维记忆图存储

数据模型完全对齐 MAGMA 论文：
  n_i = <c_i, τ_i, v_i, A_i>

四种边类型：TEMPORAL / CAUSAL / SEMANTIC / ENTITY
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


# ── Enums ────────────────────────────────────────────────────────

class NodeType(Enum):
    EVENT = "EVENT"
    ENTITY = "ENTITY"
    EPISODE = "EPISODE"

class LinkType(Enum):
    TEMPORAL = "TEMPORAL"   # 时间边 — 自动创建，不可变
    CAUSAL = "CAUSAL"       # 因果边 — 慢路径 LLM 推断
    SEMANTIC = "SEMANTIC"   # 语义边 — cosine > 阈值
    ENTITY = "ENTITY"       # 实体边 — 事件↔实体

class LinkSubType(Enum):
    # Temporal
    PRECEDES = "PRECEDES"
    SUCCEEDS = "SUCCEEDS"
    # Causal
    LEADS_TO = "LEADS_TO"
    BECAUSE_OF = "BECAUSE_OF"
    ENABLES = "ENABLES"
    PREVENTS = "PREVENTS"
    # Semantic
    SIMILAR_TO = "SIMILAR_TO"
    RELATED_TO = "RELATED_TO"
    # Entity
    REFERS_TO = "REFERS_TO"
    MENTIONED_IN = "MENTIONED_IN"


# ── Data classes ─────────────────────────────────────────────────

@dataclass
class EventNode:
    """
    MAGMA 论文公式 (3):
    n_i = <c_i, τ_i, v_i, A_i>
    """
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_type: NodeType = NodeType.EVENT
    content_narrative: str = ""           # c_i — 事件内容
    timestamp: datetime = field(default_factory=datetime.now)  # τ_i
    embedding_vector: Optional[List[float]] = None  # v_i — 向量（存引用）
    attributes: Dict[str, Any] = field(default_factory=dict)  # A_i
    session_id: Optional[str] = None      # 来源会话（Hermes 会话 ID）
    source: str = "agent"                 # 来源标识

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "content_narrative": self.content_narrative,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "embedding_vector": self.embedding_vector,
            "attributes": self.attributes,
            "session_id": self.session_id,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventNode:
        node = cls(
            node_id=data.get("node_id", str(uuid.uuid4())),
            content_narrative=data.get("content_narrative", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            embedding_vector=data.get("embedding_vector"),
            attributes=data.get("attributes", {}),
            session_id=data.get("session_id"),
            source=data.get("source", "agent"),
        )
        if "node_type" in data:
            node.node_type = NodeType(data["node_type"])
        return node


@dataclass
class Link:
    """边 — 链接两个节点"""
    source_id: str                         # 源节点 ID
    target_id: str                         # 目标节点 ID
    link_type: LinkType                    # 四种边类型之一
    sub_type: Optional[LinkSubType] = None # 子类型
    weight: float = 1.0                    # 边权重
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "link_type": self.link_type.value,
            "sub_type": self.sub_type.value if self.sub_type else None,
            "weight": self.weight,
            "metadata": self.metadata,
        }


# ── Graph Database Interface ────────────────────────────────────

class GraphDB:
    """
    内存图数据库，NetworkX 实现。
    存储 EventNode + Link，支持四种边的 CRUD 和遍历。
    """

    def __init__(self):
        self._nodes: Dict[str, EventNode] = {}   # node_id → EventNode
        self._edges: Dict[str, List[Link]] = {}  # node_id → 出边列表
        self._entity_nodes: Dict[str, EventNode] = {}  # entity_name → ENTITY 节点

    # ── Node operations ──────────────────────────────────────────

    def add_node(self, node: EventNode) -> str:
        self._nodes[node.node_id] = node
        if node.node_type == NodeType.ENTITY:
            name = node.attributes.get("entity_name", node.node_id)
            self._entity_nodes[name] = node
        return node.node_id

    def get_node(self, node_id: str) -> Optional[EventNode]:
        return self._nodes.get(node_id)

    def get_entity_node(self, name: str) -> Optional[EventNode]:
        return self._entity_nodes.get(name)

    def get_all_nodes(self) -> List[EventNode]:
        return list(self._nodes.values())

    def get_event_nodes(self) -> List[EventNode]:
        return [n for n in self._nodes.values() if n.node_type == NodeType.EVENT]

    def node_count(self) -> int:
        return len(self._nodes)

    # ── Edge operations ──────────────────────────────────────────

    def add_edge(self, link: Link) -> None:
        if link.source_id not in self._edges:
            self._edges[link.source_id] = []
        self._edges[link.source_id].append(link)

    def get_outgoing_edges(self, node_id: str) -> List[Link]:
        return self._edges.get(node_id, [])

    def get_neighbors(self, node_id: str, link_type: Optional[LinkType] = None) -> List[Tuple[str, Link]]:
        """获取邻居节点 (node_id, edge_link)"""
        neighbors = []
        for link in self.get_outgoing_edges(node_id):
            if link_type is None or link.link_type == link_type:
                neighbors.append((link.target_id, link))
        return neighbors

    def get_edges_by_type(self, link_type: LinkType) -> List[Link]:
        result = []
        for edges in self._edges.values():
            for e in edges:
                if e.link_type == link_type:
                    result.append(e)
        return result

    def edge_count(self) -> int:
        return sum(len(edges) for edges in self._edges.values())

    def get_subgraph(self, node_ids: Set[str], max_hops: int = 2) -> Tuple[List[EventNode], List[Link]]:
        """
        取节点集的子图（节点 + 连接它们的边）
        """
        nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
        edges = []
        visited = set(node_ids)
        frontier = set(node_ids)

        for _ in range(max_hops):
            if not frontier:
                break
            next_frontier = set()
            for nid in frontier:
                for link in self.get_outgoing_edges(nid):
                    if link.target_id not in visited:
                        visited.add(link.target_id)
                        next_frontier.add(link.target_id)
                    edges.append(link)
            frontier = next_frontier

        result_nodes = [self._nodes[nid] for nid in visited if nid in self._nodes]
        return result_nodes, edges

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "edges": [
                e.to_dict() for edges in self._edges.values() for e in edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GraphDB:
        db = cls()
        for node_data in data.get("nodes", {}).values():
            db.add_node(EventNode.from_dict(node_data))
        for edge_data in data.get("edges", []):
            link_type = LinkType(edge_data["link_type"])
            sub_type = LinkSubType(edge_data["sub_type"]) if edge_data.get("sub_type") else None
            db.add_edge(Link(
                source_id=edge_data["source_id"],
                target_id=edge_data["target_id"],
                link_type=link_type,
                sub_type=sub_type,
                weight=edge_data.get("weight", 1.0),
                metadata=edge_data.get("metadata", {}),
            ))
        return db
