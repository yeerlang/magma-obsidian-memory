"""
MAGMA 核心记忆引擎 — TRGMemory 实现

MAGMA 论文三层架构的核心：
- Data Structure Layer: GraphDB + VectorDB
- Write/Update Process: 快路径 + 慢路径
- Query Process: RRF → Beam Search → 线性化

对齐论文公式 (3) n_i = <c_i, τ_i, v_i, A_i>
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import deque
from datetime import datetime
from threading import Thread, Event
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv
import os

from .graph_db import GraphDB, EventNode, Link, NodeType, LinkType, LinkSubType
from .vector_db import VectorDB

load_dotenv()
logger = logging.getLogger(__name__)


class TRGMemory:
    """
    Temporal Resonance Graph Memory — 核心记忆引擎

    论文架构中的 Data Structure Layer + Write/Update Process。
    """

    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        # ── 存储层 ──
        self.graph_db = GraphDB()
        self.vector_db = VectorDB(dimension=384)

        # ── 慢路径队列 (论文 Algorithm 2 line 10) ──
        self._consolidation_queue: deque = deque()

        # ── Embedding ──
        self._encoder = None
        self._embedding_model = embedding_model
        self._encoder_fitted = True  # sentence-transformers 不需要 fit

        # ── LLM（DeepSeek，用于因果/实体推断） ──
        self._llm_client = None

        # ── 统计 ──
        self.stats = {
            "events_added": 0,
            "links_created": 0,
            "queries_processed": 0,
        }

    # ── LLM lazy init ────────────────────────────────────────────

    def _get_llm(self):
        if self._llm_client is None:
            from openai import OpenAI
            api_key = os.getenv("DEEPSEEK_API_KEY")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            self._llm_client = OpenAI(api_key=api_key, base_url=base_url)
            self._llm_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        return self._llm_client

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(self._embedding_model)
        return self._encoder

    def warmup(self):
        """预热：预加载 encoder 模型，避免首次请求阻塞。"""
        self._get_encoder()
        logger.info("MAGMA encoder warmed up")

    # ── 快路径：写入事件（MAGMA Algorithm 2） ────────────────────

    def add_event(
        self,
        content: str,
        timestamp: Optional[datetime] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        写入一个事件（快路径）

        对应论文 Algorithm 2 (Fast Path: Synaptic Ingestion):
        1. SegmentEvent → 创建事件节点
        2. 编码 v_i
        3. 存向量库
        4. 加时间边
        5. 返回节点 ID
        """
        # 创建事件节点
        node = EventNode(
            content_narrative=content,
            timestamp=timestamp or datetime.now(),
            attributes=metadata or {},
            session_id=session_id,
        )

        # 生成 embedding（sentence-transformers 语义向量）
        encoder = self._get_encoder()
        vec = encoder.encode(content).tolist()
        node.embedding_vector = vec

        # 存入图
        self.graph_db.add_node(node)

        # 存入向量库
        self.vector_db.add(node.node_id, vec)

        # 加时间边：连到最后一个事件
        all_events = self.graph_db.get_event_nodes()
        if len(all_events) >= 2:
            prev = all_events[-2]
            self.graph_db.add_edge(Link(
                source_id=prev.node_id,
                target_id=node.node_id,
                link_type=LinkType.TEMPORAL,
                sub_type=LinkSubType.PRECEDES,
            ))
            self.graph_db.add_edge(Link(
                source_id=node.node_id,
                target_id=prev.node_id,
                link_type=LinkType.TEMPORAL,
                sub_type=LinkSubType.SUCCEEDS,
            ))
            self.stats["links_created"] += 2

        self.stats["events_added"] += 1

        # 论文 Algorithm 2 line 10: 入队触发慢路径
        self._consolidation_queue.append(node.node_id)

        return node.node_id

    # ── G6: SegmentEvent (论文 Algorithm 2 line 3) ─────────────────

    @staticmethod
    def _segment_content(content: str, min_chars: int = 5) -> List[str]:
        """将长文本按句子边界分割成离散事件段。"""
        # 按句末标点分行
        raw = re.split(r'(?<=[。！？\n])\s*', content)
        segments = []
        buf = ""
        for part in raw:
            part = part.strip()
            if not part:
                continue
            buf = (buf + part) if buf else part
            # 段末标点或缓冲区够长就切
            if buf.endswith(('。', '！', '？')) or len(buf) >= 80:
                if len(buf) >= min_chars:
                    segments.append(buf)
                buf = ""
        if buf and len(buf) >= min_chars:
            segments.append(buf)
        return segments if segments else [content] if content.strip() else []

    def add_events_segmented(
        self,
        content: str,
        timestamp: Optional[datetime] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """G6: 长文本自动分段 → 批量写入离散事件。

        返回所有创建的事件 node_id 列表。
        """
        segments = self._segment_content(content)
        node_ids = []
        for seg in segments:
            nid = self.add_event(
                content=seg,
                timestamp=timestamp,
                session_id=session_id,
                metadata=metadata,
            )
            node_ids.append(nid)
        return node_ids

    # ── 语义边构建 ──────────────────────────────────────────────

    def build_semantic_edges(self, threshold: float = 0.7) -> int:
        """
        论文：语义边 = cos(v_i, v_j) > θ_sim

        在事件节点之间加语义边。
        """
        import numpy as np
        events = self.graph_db.get_event_nodes()
        count = 0

        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                vi = events[i].embedding_vector
                vj = events[j].embedding_vector
                if vi is None or vj is None:
                    continue
                vi_n = np.array(vi) / (np.linalg.norm(vi) + 1e-10)
                vj_n = np.array(vj) / (np.linalg.norm(vj) + 1e-10)
                sim = float(np.dot(vi_n, vj_n))
                if sim > threshold:
                    self.graph_db.add_edge(Link(
                        source_id=events[i].node_id,
                        target_id=events[j].node_id,
                        link_type=LinkType.SEMANTIC,
                        sub_type=LinkSubType.SIMILAR_TO,
                        weight=sim,
                    ))
                    count += 1

        self.stats["links_created"] += count
        return count

    # ── 慢路径：因果/实体推断 ────────────────────────────────────

    def infer_causal_and_entity_edges(self, node_id: str) -> Dict[str, int]:
        """
        论文 Algorithm 3 (Slow Path: Structural Consolidation):
        对某个节点的 2-hop 邻居子图，用 LLM 推断因果和实体边

        P4 增强：注入 wiki 知识上下文以对抗幻觉（论文 Limitation #1）

        返回: {"causal": N, "entity": N}
        """
        sub_nodes, sub_edges = self.graph_db.get_subgraph({node_id}, max_hops=2)

        # 构建提示词
        context_parts = []
        for n in sub_nodes[:20]:  # token 限制
            context_parts.append(f"[{n.node_id[:8]}] {n.content_narrative[:200]}")

        # P4: 检索相关 wiki 页面作为知识接地
        wiki_context = ""
        try:
            target_node = self.graph_db.get_node(node_id)
            if target_node and target_node.embedding_vector:
                # Search vector DB for wiki-ingest nodes
                wiki_results = self.vector_db.search(target_node.embedding_vector, top_k=5)
                wiki_parts = []
                for nid, score in wiki_results:
                    wiki_node = self.graph_db.get_node(nid)
                    if wiki_node and wiki_node.session_id == "wiki-ingest":
                        wiki_parts.append(f"- [{score:.2f}] {wiki_node.content_narrative[:150]}")
                if wiki_parts:
                    wiki_context = f"""
相关知识（来自 Wiki，用于接地推理）：
{chr(10).join(wiki_parts)}

"""
        except Exception:
            pass  # Wiki 检索失败不阻塞

        prompt = f"""分析以下事件之间的因果关系和实体关联。
{wiki_context}事件列表：
{chr(10).join(context_parts)}

请输出：
1. 因果关系：哪些事件导致了其他事件？格式: cause_id → effect_id
2. 实体: 这些事件涉及的人名、项目名、工具名。格式: 实体: name1, name2

只输出分析结果，不要其他内容。"""

        try:
            llm = self._get_llm()
            resp = llm.chat.completions.create(
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
            )
            analysis = resp.choices[0].message.content
            logger.info(f"LLM consolidation analysis:\n{analysis[:500]}")
        except Exception as e:
            logger.warning(f"LLM inference failed: {e}")
            return {"causal": 0, "entity": 0}

        # 解析结果（简化版）
        result = {"causal": 0, "entity": 0}

        for line in analysis.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 因果边: 任何含 "→" 的行（排除格式说明行）
            if "→" in line and "格式" not in line:
                parts = line.split("→")
                if len(parts) == 2:
                    src = parts[0].strip().strip("[]").strip()
                    tgt = parts[1].strip().strip("[]").strip()
                    # 尝试匹配 node_id
                    matched_src = self._match_node_id(src, sub_nodes)
                    matched_tgt = self._match_node_id(tgt, sub_nodes)
                    if matched_src and matched_tgt:
                        self.graph_db.add_edge(Link(
                            source_id=matched_src,
                            target_id=matched_tgt,
                            link_type=LinkType.CAUSAL,
                            sub_type=LinkSubType.LEADS_TO,
                        ))
                        result["causal"] += 1

            # G1: 实体提取 — "实体: name1, name2" or "Entity: name1, name2"
            elif ("实体" in line or "entity" in line.lower() or "Entity" in line) and ":" in line:
                entity_part = line.split(":", 1)[-1] if ":" in line else line
                for name in re.split(r'[,，、]', entity_part):
                    name = name.strip().strip('"').strip("'")
                    if name and len(name) > 1:
                        entity_id = self._get_or_create_entity(name)
                        # Connect all sub_nodes to this entity
                        for sn in sub_nodes[:10]:
                            self.graph_db.add_edge(Link(
                                source_id=sn.node_id,
                                target_id=entity_id,
                                link_type=LinkType.ENTITY,
                                sub_type=LinkSubType.REFERS_TO,
                            ))
                            self.graph_db.add_edge(Link(
                                source_id=entity_id,
                                target_id=sn.node_id,
                                link_type=LinkType.ENTITY,
                                sub_type=LinkSubType.MENTIONED_IN,
                            ))
                        result["entity"] += 1

        return result

    def _get_or_create_entity(self, name: str) -> str:
        """论文 Entity Graph: 查找或创建实体节点，解决 object permanence"""
        # Search existing entities by name (case-insensitive)
        for n in self.graph_db.get_all_nodes():
            if n.node_type == NodeType.ENTITY:
                if name.lower() in n.content_narrative.lower():
                    return n.node_id

        # Create new entity node
        entity = EventNode(
            content_narrative=name,
            node_type=NodeType.ENTITY,
            attributes={"entity_name": name},
        )
        self.graph_db.add_node(entity)
        self.stats["events_added"] += 1
        return entity.node_id

    def _match_node_id(self, snippet: str, nodes: List[EventNode]) -> Optional[str]:
        """从文本片段匹配节点 ID"""
        for n in nodes:
            if n.node_id.startswith(snippet) or snippet in n.content_narrative:
                return n.node_id
        return None

    # ── 慢路径后台 Worker (论文 Algorithm 3 完整循环) ───────────

    def _consolidation_worker(self) -> None:
        """论文 Algorithm 3: 后台线程持续消费队列，对每个事件做 2-hop LLM 推断"""
        logger.info("MAGMA consolidation worker started")
        while not self._stop_event.is_set():
            try:
                # 阻塞等待，超时 5s 检查停止信号
                try:
                    node_id = self._consolidation_queue.popleft()
                except IndexError:
                    self._stop_event.wait(5)
                    continue

                logger.info(f"Consolidating: {node_id[:8]}")
                result = self.infer_causal_and_entity_edges(node_id)
                if result["causal"] or result["entity"]:
                    logger.info(
                        f"Consolidated {node_id[:8]}: "
                        f"+{result['causal']} causal, +{result['entity']} entity"
                    )
            except Exception as e:
                logger.error(f"Consolidation worker error: {e}")

        logger.info("MAGMA consolidation worker stopped")

    def start_consolidation_worker(self) -> None:
        """启动后台 consolidation worker 线程"""
        self._stop_event = Event()
        self._worker_thread = Thread(target=self._consolidation_worker, daemon=True)
        self._worker_thread.start()

    def stop_consolidation_worker(self, timeout: float = 10) -> None:
        """停止后台 worker"""
        self._stop_event.set()
        if hasattr(self, '_worker_thread') and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)

    # ── 工具方法 ──────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[EventNode]:
        return self.graph_db.get_node(node_id)

    def get_stats(self) -> Dict[str, Any]:
        stats = dict(self.stats)
        stats["nodes"] = self.graph_db.node_count()
        stats["edges"] = self.graph_db.edge_count()
        stats["vectors"] = self.vector_db.count()
        return stats

    def save_to_file(self, path: str) -> None:
        """持久化到 JSON 文件"""
        import json
        data = {
            "graph": self.graph_db.to_dict(),
            "stats": self.stats,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self, path: str) -> None:
        """从 JSON 文件加载"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.graph_db = GraphDB.from_dict(data["graph"])
        self.stats["events_added"] = data.get("stats", {}).get("events_added", 0)
        self.stats["links_created"] = data.get("stats", {}).get("links_created", 0)
