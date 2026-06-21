"""
Vector Database — 向量存储与语义检索

MAGMA 论文中的向量数据库层，用于：
- 存储事件 embedding（v_i）
- 语义相似度搜索（cosine > θ_sim）
- 返回锚点候选供 RRF 融合
"""

from __future__ import annotations

import numpy as np
from typing import List, Optional, Tuple


class VectorDB:
    """
    NumPy + FAISS 实现的向量数据库。

    论文公式：cos(v_i, v_j) > θ_sim 定义语义边
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self._vectors: List[np.ndarray] = []       # embedding 数组
        self._node_ids: List[str] = []             # 对应的节点 ID
        self._faiss_index = None
        self._use_faiss = False

    def add(self, node_id: str, vector: List[float]) -> None:
        """添加一个向量索引"""
        vec = np.array(vector, dtype=np.float32)
        self._vectors.append(vec)
        self._node_ids.append(node_id)

    def search(self, query_vector: List[float], top_k: int = 10) -> List[Tuple[str, float]]:
        """
        语义搜索，返回 [(node_id, score), ...]

        score 是 cosine 相似度 (0~1)，越高越相似。
        """
        if not self._vectors:
            return []

        q = np.array(query_vector, dtype=np.float32)
        # 归一化
        q_norm = q / (np.linalg.norm(q) + 1e-10)

        # 暴力搜索（数据量小时够用）
        scores = []
        for i, vec in enumerate(self._vectors):
            vec_norm = vec / (np.linalg.norm(vec) + 1e-10)
            sim = float(np.dot(q_norm, vec_norm))
            scores.append((self._node_ids[i], sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def get_vector(self, node_id: str) -> Optional[List[float]]:
        """获取某个节点的向量"""
        for i, nid in enumerate(self._node_ids):
            if nid == node_id:
                return self._vectors[i].tolist()
        return None

    def get_all_vectors(self) -> List[Tuple[str, List[float]]]:
        """获取所有向量"""
        return [(nid, self._vectors[i].tolist()) for i, nid in enumerate(self._node_ids)]

    def count(self) -> int:
        return len(self._node_ids)

    def clear(self) -> None:
        self._vectors.clear()
        self._node_ids.clear()

    def save(self, path: str) -> None:
        """保存向量到 .npy 文件"""
        if self._vectors:
            np.save(f"{path}/vectors.npy", np.array(self._vectors, dtype=np.float32))
        import json
        with open(f"{path}/node_ids.json", "w") as f:
            json.dump(self._node_ids, f)

    def load(self, path: str) -> None:
        """从 .npy 文件加载向量"""
        import os, json
        vec_path = f"{path}/vectors.npy"
        id_path = f"{path}/node_ids.json"
        if os.path.exists(vec_path):
            self._vectors = list(np.load(vec_path))
        if os.path.exists(id_path):
            with open(id_path) as f:
                self._node_ids = json.load(f)
