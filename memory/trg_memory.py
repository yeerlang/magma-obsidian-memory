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
import os
import time
from collections import deque
from datetime import datetime
from threading import Lock, Thread, Event
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

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
        # Queue elements are (node_id, enqueue_timestamp) tuples
        self._consolidation_queue: deque = deque()
        self._queue_lock = Lock()

        # ── Embedding ──
        self._encoder = None
        self._embedding_model = embedding_model
        self._encoder_fitted = True  # sentence-transformers 不需要 fit

        # ── LLM（DeepSeek，用于因果/实体推断） ──
        self._llm_client = None

        # ── 统计 + 线程安全 ──
        self._stats_lock = Lock()
        self.stats = {
            "events_added": 0,
            "links_created": 0,
            "queries_processed": 0,
            "total_consolidated": 0,
            "total_causal_edges": 0,
            "total_entity_edges": 0,
            "latency_count": 0,
            "latency_mean": 0.0,
            "latency_M2": 0.0,
            "worker_last_heartbeat": 0.0,
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
        # 在 MCP 长进程中 tokenizers 0.22.x 可能有状态异常，
        # 失败时重建 encoder 重试一次
        encoder = self._get_encoder()
        try:
            vec = encoder.encode(content, convert_to_numpy=True).tolist()
        except Exception:
            self._encoder = None
            encoder = self._get_encoder()
            vec = encoder.encode(content, convert_to_numpy=True).tolist()
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
            with self._stats_lock:
                self.stats["links_created"] += 2

        with self._stats_lock:
            self.stats["events_added"] += 1

        # 论文 Algorithm 2 line 10: 入队触发慢路径（带时间戳）
        with self._queue_lock:
            self._consolidation_queue.append((node.node_id, time.time()))

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

    def build_semantic_edges(self, threshold: float = 0.8, max_edges: int = 1000) -> int:
        """
        论文：语义边 = cos(v_i, v_j) > θ_sim

        智能采样策略：随机取 sqrt(n) 个锚点事件，只对锚点做全量比较。
        复杂度从 O(n²) 降至 O(n^1.5)，加 max_edges 硬上限防止边爆炸。
        max_edges: 达到上限后停止添加（去重后计数），0=无限制。
        """
        import numpy as np
        import random

        events = self.graph_db.get_event_nodes()
        n = len(events)
        if n < 2:
            return 0

        # 智能采样：sqrt(n) 个锚点，每个锚点 vs 全量事件
        n_anchors = max(1, int(n ** 0.5))
        anchors = random.sample(events, min(n_anchors, n))
        anchor_ids = {a.node_id for a in anchors}

        added = 0

        for anchor in anchors:
            if max_edges > 0 and added >= max_edges:
                break
            va = anchor.embedding_vector
            if va is None:
                continue
            va_n = np.array(va) / (np.linalg.norm(va) + 1e-10)

            for event in events:
                if max_edges > 0 and added >= max_edges:
                    break
                # 跳过自比较
                if event.node_id == anchor.node_id:
                    continue
                vj = event.embedding_vector
                if vj is None:
                    continue
                vj_n = np.array(vj) / (np.linalg.norm(vj) + 1e-10)
                sim = float(np.dot(va_n, vj_n))

                if sim > threshold:
                    if self.graph_db.add_edge(Link(
                        source_id=anchor.node_id,
                        target_id=event.node_id,
                        link_type=LinkType.SEMANTIC,
                        sub_type=LinkSubType.SIMILAR_TO,
                        weight=sim,
                    )):
                        added += 1

        with self._stats_lock:
            self.stats["links_created"] += added
        return added

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
1. 因果关系：哪些事件导致了其他事件？格式: cause_id → effect_id (confidence: 0-100)
   其中 confidence 是你对该因果关系的置信度（0=纯猜测，100=非常确定）
2. 实体: 这些事件涉及的人名、项目名、工具名。
   格式: 实体: name1 (confidence: 0-100), name2 (confidence: 0-100), ...
   其中 confidence 是你对该实体确实出现在事件中的置信度

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

        # 解析结果（论文 Section 3.4: high-value edge 过滤，confidence ≥ 70）
        result = {"causal": 0, "entity": 0}

        for line in analysis.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 因果边: 任何含 "→" 的行（排除格式说明行）
            if "→" in line and "格式" not in line:
                # 提取 confidence — 缺失时默认 50（旧格式兼容，低于 70 门槛安全跳过）
                conf_match = re.search(r'\(confidence:\s*(\d+(?:\.\d+)?)\)', line)
                confidence = float(conf_match.group(1)) if conf_match else 50.0
                if confidence < 70:
                    continue
                parts = line.split("→")
                if len(parts) == 2:
                    src = parts[0].strip().strip("[]").strip()
                    tgt = parts[1].strip().strip("[]").strip()
                    # 从 tgt 中移除 confidence 标记以便匹配 node_id
                    tgt_clean = re.sub(
                        r'\s*\(confidence:\s*\d+(?:\.\d+)?\)\s*', '', tgt
                    ).strip()
                    matched_src = self._match_node_id(src, sub_nodes)
                    matched_tgt = self._match_node_id(tgt_clean, sub_nodes)
                    if matched_src and matched_tgt:
                        self.graph_db.add_edge(Link(
                            source_id=matched_src,
                            target_id=matched_tgt,
                            link_type=LinkType.CAUSAL,
                            sub_type=LinkSubType.LEADS_TO,
                        ))
                        result["causal"] += 1

            # 实体提取 — "实体: name1 (confidence: N), name2 (confidence: N)"
            elif ("实体" in line or "entity" in line.lower() or "Entity" in line) and ":" in line:
                entity_part = line.split(":", 1)[-1] if ":" in line else line
                for segment in re.split(r'[,，、]', entity_part):
                    segment = segment.strip()
                    if not segment:
                        continue
                    # 提取 per-entity confidence — 缺失时默认 50（旧格式兼容，低于 70 安全跳过）
                    conf_match = re.search(
                        r'\(confidence:\s*(\d+(?:\.\d+)?)\)', segment
                    )
                    confidence = float(conf_match.group(1)) if conf_match else 50.0
                    if confidence < 70:
                        continue
                    # 移除 confidence 标记得到干净名称
                    name = re.sub(
                        r'\s*\(confidence:\s*\d+(?:\.\d+)?\)\s*', '', segment
                    ).strip()
                    name = name.strip('"').strip("'")
                    if name and len(name) > 1:
                        entity_id = self._get_or_create_entity(name)
                        # Paper principle: Entity edges only connect events
                        # that actually MENTION the entity — not blind fan-out.
                        entity_connected = 0
                        for sn in sub_nodes:
                            if name.lower() in sn.content_narrative.lower():
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
                                entity_connected += 1
                        if entity_connected > 0:
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
        # 实体节点是内部构造，不计入 events_added
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
                    with self._queue_lock:
                        node_id, enqueued_at = self._consolidation_queue.popleft()
                except IndexError:
                    self._stop_event.wait(5)
                    continue

                # 心跳
                with self._stats_lock:
                    self.stats["worker_last_heartbeat"] = time.time()

                t0 = time.time()
                logger.info(f"Consolidating: {node_id[:8]}")
                result = self.infer_causal_and_entity_edges(node_id)
                elapsed_ms = (time.time() - t0) * 1000.0

                # Welford 在线均值更新
                with self._stats_lock:
                    self.stats["total_consolidated"] += 1
                    self.stats["total_causal_edges"] += result["causal"]
                    self.stats["total_entity_edges"] += result["entity"]
                    # Welford: count, mean, M2
                    count = self.stats["latency_count"] + 1
                    delta = elapsed_ms - self.stats["latency_mean"]
                    self.stats["latency_mean"] += delta / count
                    self.stats["latency_M2"] += delta * (elapsed_ms - self.stats["latency_mean"])
                    self.stats["latency_count"] = count

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
        with self._stats_lock:
            stats = dict(self.stats)
        stats["nodes"] = self.graph_db.node_count()
        stats["edges"] = self.graph_db.edge_count()
        stats["vectors"] = self.vector_db.count()
        return stats

    def get_queue_oldest_age_sec(self) -> float:
        """返回队列中最老节点的等待时间（秒），队列空时为 0"""
        try:
            with self._queue_lock:
                _, enqueued_at = self._consolidation_queue[0]
            return max(0.0, time.time() - enqueued_at)
        except IndexError:
            return 0.0

    def is_worker_alive(self) -> bool:
        """检查后台 consolidation worker 线程是否存活"""
        return hasattr(self, '_worker_thread') and self._worker_thread.is_alive()

    def get_metrics(self) -> Dict[str, Any]:
        """返回 /metrics 端点的完整可观测性数据（含慢路径指标）"""
        with self._stats_lock:
            s = dict(self.stats)
        with self._queue_lock:
            qd = len(self._consolidation_queue)
        return {
            "events_added": s["events_added"],
            "links_created": s["links_created"],
            "queries_processed": s["queries_processed"],
            "nodes": self.graph_db.node_count(),
            "edges": self.graph_db.edge_count(),
            "vectors": self.vector_db.count(),
            "slow_path": {
                "queue_depth": qd,
                "queue_oldest_age_sec": self.get_queue_oldest_age_sec(),
                "total_consolidated": s["total_consolidated"],
                "total_causal_edges": s["total_causal_edges"],
                "total_entity_edges": s["total_entity_edges"],
                "avg_latency_ms": s["latency_mean"] if s["latency_count"] > 0 else None,
                "worker_alive": self.is_worker_alive(),
            },
        }

    def increment_queries_processed(self) -> None:
        """线程安全递增 queries_processed 计数器"""
        with self._stats_lock:
            self.stats["queries_processed"] += 1

    def save_to_file(self, path: str) -> None:
        """持久化到 JSON 文件"""
        import json
        with self._stats_lock:
            stats_snapshot = dict(self.stats)
        data = {
            "graph": self.graph_db.to_dict(),
            "stats": stats_snapshot,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self, path: str) -> None:
        """从 JSON 文件加载（向后兼容：缺字段默认 0）"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.graph_db = GraphDB.from_dict(data["graph"])
        saved_stats = data.get("stats", {})
        with self._stats_lock:
            for key, default in [
                ("events_added", 0), ("links_created", 0), ("queries_processed", 0),
                ("total_consolidated", 0), ("total_causal_edges", 0), ("total_entity_edges", 0),
                ("latency_count", 0), ("latency_mean", 0.0), ("latency_M2", 0.0),
                ("worker_last_heartbeat", 0.0),
            ]:
                self.stats[key] = saved_stats.get(key, default)
        # 重建 VectorDB：autosave JSON 中节点含 embedding_vector，
        # graph_db.from_dict() 已恢复该属性，但 vector_db 仍为空
        self.vector_db.clear()
        for node in self.graph_db.get_all_nodes():
            if node.embedding_vector:
                self.vector_db.add(node.node_id, node.embedding_vector)
