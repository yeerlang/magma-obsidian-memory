# 论文公式 → 代码映射

> MAGMA 论文 (arXiv 2601.03236) 每个公式到实现的逐行对应

## 公式速查表

| 公式 | 含义 | 代码位置 | 行数 |
|------|------|----------|:----:|
| (1) | 问题定义 | — | — |
| (2) | 记忆状态 | — | — |
| (3) | 事件节点定义 | `memory/graph_db.py` → `EventNode` | 51-64 |
| (4) | RRF 融合 | `memory/query_engine.py` → `find_anchors()` | 165-220 |
| (5) | Beam Search 评分 | `memory/query_engine.py` → `adaptive_traversal()` | 286 |
| (6) | 意图权重模板 | `memory/query_engine.py` → `_INTENT_WEIGHTS` | 37-62 |
| (7) | 线性化输出 | `memory/query_engine.py` → `linearize_context()` | 306-362 |

---

## 公式 (3)：事件节点

```
n_i = <c_i, τ_i, v_i, A_i>
```

### 代码实现

```python
# memory/graph_db.py:51-64
@dataclass
class EventNode:
    node_id: str                            # UUID 标识
    node_type: NodeType = NodeType.EVENT    # EVENT | ENTITY | EPISODE
    content_narrative: str = ""             # c_i — 事件内容
    timestamp: datetime = ...               # τ_i — 时间戳
    embedding_vector: Optional[List[float]] # v_i — 语义向量
    attributes: Dict[str, Any]              # A_i — 属性字典
    session_id: Optional[str] = None        # 来源会话
    source: str = "agent"                   # 来源标识
```

**对齐验证**：`c_i`=content_narrative, `τ_i`=timestamp, `v_i`=embedding_vector, `A_i`=attributes ✓

---

## 公式 (4)：RRF 多信号融合

```
S_anchor = Top_K( Σ_{m∈M} 1/(k + r_m(n)) )
```

### 代码实现

```python
# memory/query_engine.py:165-220
def find_anchors(self, query, query_vec, top_k=5, time_window=None):
    ranked_lists = []

    # Signal 1: 向量搜索
    vec_results = self.memory.vector_db.search(query_vec, top_k=20)
    # → ranked_lists[0]

    # Signal 2: 关键词搜索
    keywords = self.extract_keywords(query)
    kw_nodes = self._keyword_search(keywords)
    # → ranked_lists[1]

    # Signal 3: 时间过滤 [G5]
    if time_window:
        time_nodes = [n for n in events if start <= n.timestamp <= end]
        # → ranked_lists[2]

    # RRF 融合
    scores = {}
    for rank_list in ranked_lists:
        for rank, node in enumerate(rank_list):
            rrf_score = 1.0 / (RRF_K + rank + 1)  # k=60
            scores[node_id] += rrf_score

    return sorted(scores)[:top_k]
```

**对齐验证**：`M={向量,关键词,时间}`, `k=60`, `r_m(n)`=rank in each list ✓

---

## 公式 (5)：自适应遍历评分

```
S(n_j|n_i, q) = exp(λ₁·φ(type(e_ij), T_q) + λ₂·sim(v_j, v_q))
```

### 代码实现

```python
# memory/query_engine.py:235-302
def adaptive_traversal(self, anchor_nodes, query_vec, intent, ...):
    weights = self._INTENT_WEIGHTS.get(intent)  # 意图权重
    λ1, λ2 = 1.0, 0.8                          # 超参数

    for depth in range(max_depth):
        for current_node, parent_score in beam:
            for neighbor_id, edge in neighbors:

                # φ(r, T_q) = 公式 (6) — 边类型权重
                structural_weight = weights.get(edge.link_type, 1.0)

                # sim(v_j, v_q) — 语义相似度
                semantic_sim = cos(neighbor_vector, query_vector)

                # 公式 (5): S = exp(λ1·φ + λ2·sim)
                score = np.exp(λ1 * structural_weight + λ2 * semantic_sim)
                cumulative = parent_score * 0.9 + score
```

**对齐验证**：`λ₁=1.0`, `λ₂=0.8`, `φ`=structural_weight, `sim`=cosine ✓

---

## 公式 (6)：意图权重模板

```
φ(r, T_q) = w_Tq^T · 1_r
```

### 代码实现

```python
# memory/query_engine.py:37-62
_INTENT_WEIGHTS = {
    "WHY": {
        LinkType.CAUSAL: 3.0,      # 因果优先
        LinkType.TEMPORAL: 1.0,
        LinkType.SEMANTIC: 0.5,
        LinkType.ENTITY: 1.0,
    },
    "WHEN": {
        LinkType.TEMPORAL: 3.0,     # 时间优先
        LinkType.CAUSAL: 0.5,
        LinkType.SEMANTIC: 0.5,
        LinkType.ENTITY: 0.5,
    },
    "WHAT": {
        LinkType.SEMANTIC: 2.0,     # 语义优先
        LinkType.TEMPORAL: 1.0,
        LinkType.CAUSAL: 0.5,
        LinkType.ENTITY: 1.0,
    },
    "ENTITY": {
        LinkType.ENTITY: 3.0,       # 实体优先
        LinkType.TEMPORAL: 1.0,
        LinkType.CAUSAL: 1.0,
        LinkType.SEMANTIC: 1.0,
    },
}
```

**对齐验证**：四种意图对应四种边权重，`w_Tq` 以一维向量编码 ✓

---

## 公式 (7)：叙事合成（线性化）

```
Linearization 三阶段：
1. Topological Ordering → 按意图排序
2. Context Scaffolding → <t:τ_i> content <ref:id>
3. Salience-Based Budgeting → token 预算截断
```

### 代码实现

```python
# memory/query_engine.py:306-362
def linearize_context(self, nodes, intent, max_tokens=3000):
    # Stage 1: 拓扑排序
    if intent == "WHEN":
        nodes.sort(key=lambda n: n.timestamp)      # 时间序
    elif intent == "WHY":
        # 因果排序：原因在前，结果在后
        for n in nodes:
            for e in outgoing_edges(n):
                if e.link_type == CAUSAL:
                    causal_order.append(target)

    # Stage 2: 上下文脚手架
    for n in nodes:
        entry = f"<t:{ts}> {content[:300]} <ref:{nid[:8]}>"

    # Stage 3: Token 预算截断
    if token_estimate + entry_tokens > max_tokens:
        parts.append(f"... 省略 {remaining} 个事件 ...")
        break
```

**对齐验证**：三阶段完整实现 ✓

---

## 公式参数汇总

| 参数 | 论文 | 实现默认值 | 可调 |
|------|:----:|-----------|:----:|
| k (RRF 常数) | 60 | `RRF_K = 60` | ✓ |
| λ₁ (结构权重) | ~1.0 | 1.0 | ✗ |
| λ₂ (语义权重) | ~0.8 | 0.8 | ✗ |
| θ_sim (语义边阈值) | 0.7 | 0.7 | ✓ (API 参数) |
| γ (衰减因子) | 未明 | 0.9 | ✗ |
| beam_width | 3 | 3 | ✓ (API 参数) |
| max_depth | 3 | 3 | ✓ (API 参数) |
| budget | 30 | 30 | ✓ (API 参数) |
| max_tokens | 3000 | 3000 | ✓ (API 参数) |
