# 论文算法中文注释

> MAGMA 论文 (arXiv 2601.03236) 三组核心算法的逐行解读

---

## Algorithm 1: Adaptive Hybrid Retrieval（自适应混合检索）

论文 Section 3.3，四阶段查询的核心遍历算法。

### 伪代码 + 中文注释

```
Algorithm 1: Adaptive Hybrid Retrieval (Heuristic Beam Search)

输入:
  q         — 查询文本
  anchors   — RRF 选出的锚点节点集合
  T_q       — 意图类型 ∈ {WHY, WHEN, WHAT, ENTITY}
  B         — Beam width（束宽，默认 3）
  D         — 最大深度（默认 3）
  budget    — 检索预算（最大节点数，默认 30）

输出:
  visited_nodes  — 已访问节点列表

1.  visited ← anchors                          // 已访问集合
2.  beam ← [(n, 1.0) for n in anchors]        // (节点, 累积分数)
3.  query_vec ← encode(q)                      // 编码查询向量

4.  for depth = 1 to D:                        // 逐层遍历
5.      if |visited| >= budget: break          // 预算控制

6.      candidates ← []                        // 本层候选
7.      for (n_i, parent_score) in beam:       // 遍历当前束
8.          neighbors ← get_neighbors(n_i)     // 获取邻居

9.          for (n_j, e_ij) in neighbors:      // 遍历每条出边
10.             if n_j in visited: continue    // 避免重复

11.             // 公式 (6): 边的结构权重
12.             φ ← INTENT_WEIGHTS[T_q][e_ij.type]

13.             // 公式 (5) 的语义相似度项
14.             sim ← cosine(n_j.vec, query_vec)

15.             // 公式 (5): 联合评分
16.             S ← exp(λ₁·φ + λ₂·sim)

17.             // 累积分数（带衰减 γ=0.9）
18.             cumulative ← parent_score × 0.9 + S
19.             candidates.append((n_j, cumulative))

20.     // Top-k 剪枝
21.     candidates.sort(by cumulative, descending)
22.     beam ← candidates[:B]

23.     for (n, _) in beam:                    // 标记已访问
24.         if n not in visited:
25.             visited.add(n)
26.             all_visited.append(n)

27.     if beam is empty: break                 // 死胡同

28. return all_visited
```

### 关键设计决策

| 设计 | 原因 | 实现 |
|------|------|------|
| Beam Search 而不是 BFS | 避免组合爆炸（图可能很大） | `beam_width=3` |
| 衰减因子 γ=0.9 | 远距离节点相关性递减 | `parent_score * 0.9` |
| 预算控制 | 防止查询拖垮延迟 | `budget=30` |
| 意图权重 φ | WHY/WHEN/WHAT/ENTITY 各有偏重 | `_INTENT_WEIGHTS` |

### 代码位置

`memory/query_engine.py` → `adaptive_traversal()` (lines 235-302)

---

## Algorithm 2: Fast Path — Synaptic Ingestion（快路径：突触摄取）

论文 Section 3.4，事件写入时的即时处理流程。

### 伪代码 + 中文注释

```
Algorithm 2: Fast Path — Synaptic Ingestion

输入:
  content    — 事件文本
  timestamp  — 时间戳（可选，默认当前时间）
  session_id — 来源会话 ID（可选）
  metadata   — 附加属性（可选）

输出:
  node_id    — 新创建的事件节点 ID

1.  // Step 1: 创建事件节点（论文公式 3）
2.  node ← EventNode(
3.      content_narrative = content,           // c_i
4.      timestamp = timestamp or now(),        // τ_i
5.      attributes = metadata,                 // A_i
6.      session_id = session_id
7.  )

8.  // Step 2: 编码语义向量 v_i
9.  encoder ← SentenceTransformer('all-MiniLM-L6-v2')
10. node.embedding_vector ← encoder.encode(content)
11. //      ↑ 384 维向量，sentence-transformers

12. // Step 3: 存入图数据库
13. graph_db.add_node(node)

14. // Step 4: 存入向量数据库
15. vector_db.add(node.node_id, node.embedding_vector)

16. // Step 5: 自动创建时间边（连到上一个事件）
17. prev ← 倒数第二个事件
18. if prev exists:
19.     graph_db.add_edge(prev → node, TEMPORAL, PRECEDES)
20.     graph_db.add_edge(node → prev, TEMPORAL, SUCCEEDS)

21. // Step 6: 入队触发慢路径（论文 Algorithm 3）
22. consolidation_queue.enqueue(node.node_id)

23. return node.node_id
```

### 时间复杂度

| 步骤 | 复杂度 | 预估耗时 |
|------|--------|:------:|
| 编码 | O(L) — 句子长度 | 5-50ms |
| 存图 | O(1) | <1ms |
| 存向量 | O(D) — 维度 384 | <1ms |
| 时间边 | O(1) | <1ms |
| **总计** | | **~20ms** |

### 代码位置

`memory/trg_memory.py` → `add_event()` (lines 85-144)

---

## Algorithm 3: Slow Path — Structural Consolidation（慢路径：结构整合）

论文 Section 3.4，后台异步推断因果和实体边。

### 伪代码 + 中文注释

```
Algorithm 3: Slow Path — Structural Consolidation

输入:
  node_id   — 待整合的事件节点 ID
  graph_db  — 图数据库（共享状态）

输出:
  causal_count  — 新增因果边数
  entity_count  — 新增实体边数

// ── 主循环（后台 Worker 线程） ──

1.  while not stopped:
2.      try:
3.          node_id ← consolidation_queue.dequeue()  // 阻塞等待
4.      catch Empty:
5.          sleep(5s); continue                      // 空队列休眠

6.      result ← ConsolidateNode(node_id)            // 核心整合
7.      log(result)                                  // 记录结果


// ── ConsolidateNode(node_id) ──

8.  // Step 1: 取 2-hop 子图
9.  sub_nodes, sub_edges ← graph_db.get_subgraph(
10.     {node_id}, max_hops=2
11. )

12. // Step 2: 构建 LLM 提示词
13. prompt ← 构建提示词:
14.     "分析以下事件之间的因果关系和实体关联"
15.     + 子图事件列表（前 20 个，每个截断 200 字符）
16.     + [可选] 相关 Wiki 知识上下文（P4 增强）

17. // Step 3: LLM 推理
18. response ← LLM.chat(
19.     model = DEEPSEEK_MODEL,
20.     messages = [{role: "user", content: prompt}],
21.     temperature = 0.1,       // 低温度 → 确定性输出
22.     max_tokens = 500
23. )

24. // Step 4: 解析 LLM 输出
25. analysis ← response.choices[0].message.content
26. causal, entity ← 0, 0

27. for line in analysis.split("\n"):
28.     // 因果边: 匹配 "A → B" 模式
29.     if "→" in line and "格式" not in line:
30.         src, tgt ← parse_arrow(line)
31.         matched_src ← find_node(src, sub_nodes)
32.         matched_tgt ← find_node(tgt, sub_nodes)
33.         if matched_src and matched_tgt:
34.             graph_db.add_edge(matched_src → matched_tgt, CAUSAL, LEADS_TO)
35.             causal += 1

36.     // 实体边: 匹配 "实体: name1, name2" 模式
37.     elif "实体" in line or "entity" in line.lower():
38.         names ← parse_entity_names(line)
39.         for name in names:
40.             entity_id ← get_or_create_entity(name)  // 论文 Object Permanence
41.             for sn in sub_nodes:
42.                 graph_db.add_edge(sn → entity_id, ENTITY, REFERS_TO)
43.                 graph_db.add_edge(entity_id → sn, ENTITY, MENTIONED_IN)
44.             entity += 1

45. return {causal: causal, entity: entity}
```

### 关键设计决策

| 设计 | 原因 | 实现 |
|------|------|------|
| 2-hop 子图 | 平衡上下文丰富度和 token 成本 | `max_hops=2` |
| 低温度 (0.1) | 结构推断需要确定性而非创意 | `temperature=0.1` |
| 异步队列 | 不阻塞快路径 | `deque` + `Thread` |
| Object Permanence | 实体名去重 — 同名实体复用 | `_get_or_create_entity()` |
| fail-open | LLM 调用失败返回 0 条边，不崩溃 | try/except |

### 代码位置

- Worker: `memory/trg_memory.py` → `_consolidation_worker()` (lines 366-394)
- Consolidate: `memory/trg_memory.py` → `infer_causal_and_entity_edges()` (lines 228-337)

---

## 三算法关系图

```
POST /events
    │
    ▼
Algorithm 2 (Fast Path)      ← 同步，~20ms
    │
    │ enqueue(node_id)
    ▼
┌───────────────────────┐
│  Consolidation Queue  │
└───────────┬───────────┘
            │ dequeued in background
            ▼
Algorithm 3 (Slow Path)      ← 异步，5-60s
    │
    │ nodes + edges in graph
    ▼
Algorithm 1 (Beam Search)    ← 查询时，~50ms
    │ 遍历四图
    ▼
  线性化输出
```
