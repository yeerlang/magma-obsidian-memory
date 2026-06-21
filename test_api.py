"""MAGMA API 端点集成测试"""
import requests, json

BASE = "http://localhost:8765"

def t(name, method, path, **kwargs):
    fn = getattr(requests, method.lower())
    url = f"{BASE}{path}"
    try:
        r = fn(url, **kwargs, timeout=10)
        print(f"[{r.status_code}] {method} {path}  ", end="")
        if r.ok:
            print(r.text[:200])
        else:
            print(f"FAIL: {r.text[:200]}")
    except Exception as e:
        print(f"[ERR] {method} {path}  {e}")

# 1) 健康检查
t("health", "GET", "/health")

# 2) 写 3 个事件
ids = []
for content in [
    "成功从 HuggingFace 下载了 sentence-transformers 模型并完成配置",
    "embedding 方案从 TF-IDF 切换到 sentence-transformers，语义向量质量提升",
    "FastAPI 接口封装完成，包括 /events /query /stats /save /load 等端点",
]:
    t("create event", "POST", "/events", json={"content": content, "session_id": "session-001"})
    # 手动解析 id
    r = requests.post(f"{BASE}/events", json={"content": content, "session_id": "session-001"}, timeout=10)
    if r.ok:
        ids.append(r.json()["node_id"])

# 3) 列事件
t("list events", "GET", "/events?limit=10")

# 4) 查单个事件
if ids:
    t("get event", "GET", f"/events/{ids[0]}")

# 5) 查询
t("query", "POST", "/query", json={"query": "sentence-transformers 下载", "top_k": 3})

# 6) 语义边
t("semantic edges", "POST", "/events/semantic-edges", json={"threshold": 0.3})

# 7) 统计
t("stats", "GET", "/stats")

# 8) 保存
t("save", "POST", "/save?filename=test_m3.json")

print("\nDone.")
