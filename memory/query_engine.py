"""
Query Engine — 自适应层次化检索

MAGMA 论文 3.3 节 Query Process，4 个阶段：
1. Query Analysis & Decomposition (意图分类 + 时序解析)
2. Multi-Signal Anchor Identification (RRF 融合)
3. Adaptive Traversal Policy (Heuristic Beam Search)
4. Narrative Synthesis (Graph Linearization)

论文公式 (4)(5)(6)(7) 全部对齐。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime, timedelta

from .graph_db import GraphDB, EventNode, Link, NodeType, LinkType
from .trg_memory import TRGMemory
import numpy as np

logger = logging.getLogger(__name__)


class QueryEngine:
    """
    MAGMA 查询引擎。

    论文 Fig.3 所示的 4 阶段流水线：
    意图检测 → RRF 锚点 → Beam Search 遍历 → 线性化输出
    """

    # 论文公式 (6) 的意图权重模板
    _INTENT_WEIGHTS = {
        "WHY": {   # 因果问题 → 优先走因果边
            LinkType.CAUSAL: 3.0,
            LinkType.TEMPORAL: 1.0,
            LinkType.SEMANTIC: 0.5,
            LinkType.ENTITY: 1.0,
        },
        "WHEN": {  # 时间问题 → 优先走时间边
            LinkType.TEMPORAL: 3.0,
            LinkType.CAUSAL: 0.5,
            LinkType.SEMANTIC: 0.5,
            LinkType.ENTITY: 0.5,
        },
        "WHAT": {  # 事实问题 → 优先走语义边
            LinkType.SEMANTIC: 2.0,
            LinkType.TEMPORAL: 1.0,
            LinkType.CAUSAL: 0.5,
            LinkType.ENTITY: 1.0,
        },
        "ENTITY": { # 实体问题 → 优先走实体边
            LinkType.ENTITY: 3.0,
            LinkType.TEMPORAL: 1.0,
            LinkType.CAUSAL: 1.0,
            LinkType.SEMANTIC: 1.0,
        },
    }

    # RRF 常数 (论文公式 4)
    RRF_K = 60

    def __init__(self, memory: TRGMemory):
        self.memory = memory

    # ── G4: 时间解析器 ─────────────────────────────────────────────

    @staticmethod
    def parse_temporal(query: str) -> Optional[Tuple[datetime, datetime]]:
        """
        论文 Stage 1b: 相对时间表达式 → 绝对时间窗口

        支持中文: 昨天/今天/明天/上周/本周/下周/上月/本月/下月/X天前/X小时前/X分钟前
        返回 (start, end) 或 None（无法解析时）
        """
        now = datetime.now()
        q = query.lower().strip()

        patterns = [
            (r"今天", now.replace(hour=0, minute=0, second=0), now),
            (r"昨天", now.replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=1),
             now.replace(hour=0, minute=0, second=0, microsecond=0)),
            (r"明天", now.replace(hour=0, minute=0, second=0),
             now.replace(hour=23, minute=59, second=59) + timedelta(days=1)),
            (r"上周", now - timedelta(days=now.weekday() + 7),
             now - timedelta(days=now.weekday() + 1)),
            (r"本周", now - timedelta(days=now.weekday()), now),
            (r"下周",
             now - timedelta(days=now.weekday()) + timedelta(days=7),
             now - timedelta(days=now.weekday()) + timedelta(days=13)),
            (r"上月",
             (now.replace(day=1) - timedelta(days=1)).replace(day=1),
             now.replace(day=1)),
            (r"本月", now.replace(day=1), now),
            (r"下月",
             (now.replace(day=1) + timedelta(days=32)).replace(day=1),
             (now.replace(day=1) + timedelta(days=62)).replace(day=1)),
            (r"(\d+)\s*天前",
             lambda m: now - timedelta(days=int(m.group(1))),
             lambda m: now),
            (r"(\d+)\s*小时前",
             lambda m: now - timedelta(hours=int(m.group(1))),
             lambda m: now),
            (r"(\d+)\s*分钟前",
             lambda m: now - timedelta(minutes=int(m.group(1))),
             lambda m: now),
        ]

        for pattern, start, end in patterns:
            match = re.search(pattern, q)
            if match:
                s = start(match) if callable(start) else start
                e = end(match) if callable(end) else end
                return (s, e)

        return None

    # ── Stage 1: 意图检测 ────────────────────────────────────────

    def classify_intent(self, query: str) -> str:
        """
        论文 Stage 1: Intent Classification
        T_q ∈ {Why, When, What, Entity}

        轻量级规则分类器（论文说的"lightweight classifier"）。
        """
        q = query.lower().strip()

        # Entity: 问"关于谁""关于什么项目"
        if q.startswith(("who", "whom", "whose", "关于谁", "关于什么", "谁的")):
            return "ENTITY"
        if re.search(r"(提到|涉及|关于)\s*(谁|什么|哪)", q):
            return "ENTITY"

        # When: 问时间
        if q.startswith(("when", "什么时候", "几点", "哪一天", "何时")):
            return "WHEN"
        if re.search(r"(上周|昨天|今天|之前|之后|什么时候|时间)", q):
            return "WHEN"

        # Why: 问原因
        if q.startswith(("why", "为什么", "怎么导致", "原因", "为何")):
            return "WHY"

        # Default: What
        return "WHAT"

    def extract_keywords(self, query: str) -> List[str]:
        """提取关键词用于精确匹配"""
        # 去除常见停用词
        stop_words = {"的", "了", "是", "在", "有", "和", "就", "不", "人", "都",
                      "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
                      "会", "着", "没有", "看", "好", "自己", "这", "那", "什么",
                      "怎么", "为什么", "如何", "吗", "啊", "呢", "吧"}
        words = re.findall(r'[\w\u4e00-\u9fff]+', query.lower())
        return [w for w in words if w not in stop_words and len(w) > 1]

    # ── Stage 2: RRF 锚点定位 ────────────────────────────────────

    def find_anchors(self, query: str, query_vec: List[float], top_k: int = 5,
                     time_window: Optional[Tuple[datetime, datetime]] = None) -> List[EventNode]:
        """
        论文公式 (4): S_anchor = Top_K(Σ 1/(k + r_m(n)))

        融合三条信号源：向量搜索 + 关键词搜索 + 时间过滤 (G5)
        """
        ranked_lists = []

        # 1. 向量搜索
        vec_results = self.memory.vector_db.search(query_vec, top_k=20)
        if vec_results:
            nodes = []
            for nid, score in vec_results:
                n = self.memory.graph_db.get_node(nid)
                if n:
                    nodes.append(n)
            ranked_lists.append(nodes)

        # 2. 关键词搜索
        keywords = self.extract_keywords(query)
        if keywords:
            kw_nodes = self._keyword_search(keywords)
            if kw_nodes:
                ranked_lists.append(kw_nodes)

        # G5: 3. 时间过滤信号 — 论文 Eq (4) 第三条信号源
        if time_window:
            start_t, end_t = time_window
            time_nodes = [
                n for n in self.memory.graph_db.get_event_nodes()
                if n.timestamp and start_t <= n.timestamp <= end_t
            ]
            if time_nodes:
                # 时间越近权重越高
                time_nodes.sort(key=lambda n: n.timestamp or datetime.min, reverse=True)
                ranked_lists.append(time_nodes[:20])

        if not ranked_lists:
            nodes = self.memory.graph_db.get_event_nodes()
            return nodes[:top_k]

        # RRF 融合
        scores = {}
        for rank_list in ranked_lists:
            for rank, node in enumerate(rank_list):
                nid = node.node_id
                rrf_score = 1.0 / (self.RRF_K + rank + 1)
                if nid in scores:
                    existing, existing_score = scores[nid]
                    scores[nid] = (existing, existing_score + rrf_score)
                else:
                    scores[nid] = (node, rrf_score)

        sorted_nodes = sorted(scores.values(), key=lambda x: x[1], reverse=True)
        return [n for n, _ in sorted_nodes[:top_k]]

    def _keyword_search(self, keywords: List[str]) -> List[EventNode]:
        """关键词精确匹配搜索"""
        matched = []
        for node in self.memory.graph_db.get_event_nodes():
            content = node.content_narrative.lower()
            score = sum(1 for kw in keywords if kw.lower() in content)
            if score > 0:
                matched.append((node, score))
        matched.sort(key=lambda x: x[1], reverse=True)
        return [n for n, _ in matched[:20]]

    # ── Stage 3: 自适应 Beam Search 遍历 ─────────────────────────

    def adaptive_traversal(
        self,
        anchor_nodes: List[EventNode],
        query_vec: List[float],
        intent: str,
        beam_width: int = 3,
        max_depth: int = 3,
        budget: int = 30,
    ) -> List[EventNode]:
        """
        论文 Algorithm 1: Adaptive Hybrid Retrieval (Heuristic Beam Search)

        论文公式 (5): S(n_j|n_i,q) = exp(λ₁·φ(type(e_ij),T_q) + λ₂·sim(⏭n_j,⏭q))
        """
        weights = self._INTENT_WEIGHTS.get(intent, self._INTENT_WEIGHTS["WHAT"])
        λ1, λ2 = 1.0, 0.8

        # 初始化
        visited = set(n.node_id for n in anchor_nodes)
        frontier = list(anchor_nodes)
        all_visited = list(anchor_nodes)
        beam = [(n, 1.0) for n in anchor_nodes]  # (node, cumulative_score)

        for depth in range(max_depth):
            if len(all_visited) >= budget:
                break

            candidates = []  # (node, cumulative_score)
            for current_node, parent_score in beam:
                neighbors = self.memory.graph_db.get_neighbors(current_node.node_id)

                for neighbor_id, edge in neighbors[:10]:  # 限制邻居数
                    if neighbor_id in visited:
                        continue

                    neighbor = self.memory.graph_db.get_node(neighbor_id)
                    if neighbor is None:
                        continue

                    # 论文公式 (6): φ(r, T_q) = w_T_q^T · 1_r
                    structural_weight = weights.get(edge.link_type, 1.0)

                    # 论文公式 (5) 的 sim 项
                    if neighbor.embedding_vector and query_vec:
                        nv = np.array(neighbor.embedding_vector) / (np.linalg.norm(neighbor.embedding_vector) + 1e-10)
                        qv = np.array(query_vec) / (np.linalg.norm(query_vec) + 1e-10)
                        semantic_sim = float(np.dot(nv, qv))
                    else:
                        semantic_sim = 0.0

                    # 论文公式 (5): S = exp(λ1·φ + λ2·sim)
                    score = np.exp(λ1 * structural_weight + λ2 * semantic_sim)
                    cumulative = parent_score * 0.9 + score  # 衰减 γ = 0.9
                    candidates.append((neighbor, cumulative))

            # 取 top-k (beam_width)
            candidates.sort(key=lambda x: x[1], reverse=True)
            beam = candidates[:beam_width]

            for n, _ in beam:
                if n.node_id not in visited:
                    visited.add(n.node_id)
                    all_visited.append(n)

            if not beam:
                break

        return all_visited

    # ── Stage 4: 叙事合成 ───────────────────────────────────────

    def linearize_context(
        self,
        nodes: List[EventNode],
        intent: str,
        max_tokens: int = 3000,
    ) -> str:
        """
        论文 Stage 4 + 公式 (7):

        1. Topological Ordering: 按时间/因果拓扑排序
        2. Context Scaffolding: <t:τ_i> content <ref:id>
        3. Salience-Based Token Budgeting: 低分节点压缩
        """
        if not nodes:
            return ""

        # 1. 拓扑排序
        if intent == "WHEN":
            nodes.sort(key=lambda n: n.timestamp if n.timestamp else datetime.min)
        elif intent == "WHY":
            # 因果排序：原因在前，结果在后
            causal_order = []
            remaining = set(n.node_id for n in nodes)
            for n in nodes:
                edges = self.memory.graph_db.get_outgoing_edges(n.node_id)
                for e in edges:
                    if e.link_type == LinkType.CAUSAL and e.target_id in remaining:
                        if n not in causal_order:
                            causal_order.append(n)
                        target = self.memory.graph_db.get_node(e.target_id)
                        if target and target not in causal_order:
                            causal_order.append(target)
                            remaining.discard(target)
                        remaining.discard(n.node_id)
            for n in nodes:
                if n not in causal_order:
                    causal_order.append(n)
            nodes = causal_order
        # else WHAT/ENTITY: 保持 RRF 排序

        # 2. 线性化 (公式 7)
        parts = []
        token_estimate = 0
        for n in nodes:
            ts = n.timestamp.strftime("%Y-%m-%d %H:%M") if n.timestamp else "unknown"
            entry = f"<t:{ts}> {n.content_narrative[:300]} <ref:{n.node_id[:8]}>"
            entry_tokens = len(entry) // 2  # 粗略估计

            if token_estimate + entry_tokens > max_tokens:
                remaining_count = len(nodes) - len(parts)
                parts.append(f"... 省略 {remaining_count} 个事件 ...")
                break

            parts.append(entry)
            token_estimate += entry_tokens

        return "\n".join(parts)

    # ── 完整查询流水线 ────────────────────────────────────────────

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        beam_width: int = 3,
        max_depth: int = 3,
        budget: int = 30,
        max_tokens: int = 3000,
    ) -> Dict[str, Any]:
        """
        完整 4 阶段查询。

        返回:
        {
            "intent": "WHY/WWHEN/WWHAT/ENTITY",
            "anchors": N,
            "retrieved_nodes": N,
            "context": "线性化文本",
            "statistics": {...}
        }
        """
        # Stage 1: 意图检测 + 时间解析 (G4)
        intent = self.classify_intent(query_text)
        time_window = self.parse_temporal(query_text)

        # 生成查询向量（sentence-transformers）
        encoder = self.memory._get_encoder()
        query_vec = encoder.encode(query_text).tolist()

        # Stage 2: RRF 锚点 (含 G5 时间信号)
        anchors = self.find_anchors(query_text, query_vec, top_k=top_k,
                                    time_window=time_window)

        if not anchors:
            return {
                "intent": intent,
                "anchors": 0,
                "retrieved_nodes": 0,
                "context": "",
                "statistics": {"query": query_text},
            }

        # Stage 3: 自适应图遍历
        retrieved = self.adaptive_traversal(
            anchors, query_vec, intent,
            beam_width=beam_width,
            max_depth=max_depth,
            budget=budget,
        )

        # Stage 4: 线性化
        context = self.linearize_context(retrieved, intent, max_tokens=max_tokens)

        self.memory.stats["queries_processed"] += 1

        return {
            "intent": intent,
            "anchors": len(anchors),
            "retrieved_nodes": len(retrieved),
            "context": context,
            "statistics": {
                "query": query_text,
                "time_window": f"{time_window[0].isoformat()}/{time_window[1].isoformat()}" if time_window else None,
                "nodes_in_graph": self.memory.graph_db.node_count(),
                "edges_in_graph": self.memory.graph_db.edge_count(),
            },
        }
