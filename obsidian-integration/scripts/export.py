#!/usr/bin/env python3
"""MAGMA Graph -> Obsidian — export memory nodes/edges as wikilinked markdown.

Creates under vault magma/graph/:
- nodes/*.md — one file per event node with frontmatter
- Each node file links to neighbors via [[wikilinks]]
- Visitable in Obsidian Graph View

Usage: python obsidian-integration/scripts/export.py
Set OBSIDIAN_VAULT_PATH in .env or as environment variable.
"""

import os, sys, json, re, urllib.request
from pathlib import Path
from datetime import datetime
from collections import defaultdict

MAGMA_API = os.environ.get("MAGMA_API", "http://localhost:8765")

VAULT = os.environ.get("OBSIDIAN_VAULT_PATH")
if not VAULT:
    print("ERROR: OBSIDIAN_VAULT_PATH not set. Set it in .env or as environment variable.")
    sys.exit(1)

GRAPH_DIR = Path(VAULT) / "magma" / "graph"
NODES_DIR = GRAPH_DIR / "nodes"

GRAPH_TYPES = {
    "SEMANTIC": "Semantic",
    "TEMPORAL": "Temporal",
    "CAUSAL": "Causal",
    "ENTITY": "Entity",
}


def api_get(path):
    url = f"{MAGMA_API}{path}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def safe_slug(text):
    """Make a safe Obsidian filename from text."""
    slug = text[:60].strip()
    slug = re.sub(r'[\\/:*?"<>|#\[\]]', '-', slug)
    slug = re.sub(r'\s+', '-', slug)
    return slug


def main():
    events = api_get("/events?limit=100")
    os.makedirs(NODES_DIR, exist_ok=True)

    stats = api_get("/stats")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    node_files = []
    for e in events:
        nid = e["node_id"]
        content = e.get("content", "")
        ts = e.get("timestamp", "")[:16].replace("T", " ")
        node_type = e.get("node_type", "EVENT")
        session_id = e.get("session_id", "")
        attrs = e.get("attributes", {})

        slug = safe_slug(content) if content else nid[:8]
        filename = f"{slug}-{nid[:8]}.md"

        tags = ["magma-node"]
        if "wiki" in str(session_id):
            tags.append("wiki-ingest")

        lines = [
            "---",
            f'title: "{content[:80]}"',
            "type: magma-node",
            f"tags: [{', '.join(tags)}]",
            f"node_id: {nid}",
            f"timestamp: {ts}",
            f"node_type: {node_type}",
            f"session: {session_id}",
            "---",
            "",
            f"# {content[:120]}",
            "",
            f"**Node ID:** `{nid}`",
            f"**Time:** {ts}",
            f"**Type:** {node_type}",
            f"**Session:** {session_id}",
            "",
        ]

        wiki_path = attrs.get("wiki_path", "")
        if wiki_path:
            lines.append(f"**Wiki:** [[{wiki_path}]]")
            lines.append("")

        wikilinks = attrs.get("wikilinks", [])
        if wikilinks:
            lines.append("## Wiki Links")
            for wl in wikilinks[:10]:
                lines.append(f"- [[{wl}]]")
            lines.append("")

        lines.extend([
            "## Content",
            "",
            content[:1000],
            "",
            "---",
            f"> Auto-generated | Nodes: {stats['nodes']} | Edges: {stats['edges']}",
        ])

        path = NODES_DIR / filename
        path.write_text("\n".join(lines), encoding="utf-8")
        node_files.append(filename)

    # Graph overview index
    meta_lines = [
        "---",
        "title: MAGMA Memory Graph",
        f"updated: {now}",
        "type: query",
        "tags: [magma, graph, visualization]",
        "---",
        "",
        "# MAGMA Memory Graph",
        "",
        f"> {stats['nodes']} nodes · {stats['edges']} edges · {len(node_files)} files",
        "",
        "## Four-Graph Overview",
        "",
        "| Graph | Type | Nodes |",
        "|-------|------|-------|",
        f"| Semantic | undirected | {stats['nodes']} |",
        f"| Temporal | directed (time) | {stats['nodes']} |",
        f"| Causal | directed (LLM) | N/A |",
        f"| Entity | directed | N/A |",
        "",
        "## All Nodes",
        "",
    ]

    by_session = defaultdict(list)
    for f in node_files:
        sid = "unknown"
        content = (NODES_DIR / f).read_text(encoding="utf-8")
        m = re.search(r'^session:\s*(.+)$', content, re.MULTILINE)
        if m:
            sid = m.group(1).strip()
        by_session[sid].append(f)

    for sid, files in sorted(by_session.items()):
        meta_lines.append(f"### {sid} ({len(files)})")
        for f in files:
            meta_lines.append(f"- [[magma/graph/nodes/{f.replace('.md','')}]]")

    meta_path = GRAPH_DIR / "graph-index.md"
    meta_path.write_text("\n".join(meta_lines), encoding="utf-8")
    print(f"[OK] {len(node_files)} node files -> {NODES_DIR}")
    print(f"     Index -> {meta_path}")


if __name__ == "__main__":
    main()
