#!/usr/bin/env python3
"""MAGMA Wiki Ingest — feed Obsidian wiki pages as MAGMA entity nodes.

Reads all .md pages from the wiki, extracts frontmatter,
and sends them to MAGMA as entity events.

Usage: python obsidian-integration/scripts/ingest.py
Set OBSIDIAN_VAULT_PATH in .env or as environment variable.
"""

import os, sys, json, re, urllib.request
from pathlib import Path

MAGMA_API = os.environ.get("MAGMA_API", "http://localhost:8765")

VAULT = os.environ.get("OBSIDIAN_VAULT_PATH")
if not VAULT:
    print("ERROR: OBSIDIAN_VAULT_PATH not set. Set it in .env or as environment variable.")
    sys.exit(1)
WIKI = Path(VAULT)

# Default page directories — customize for your vault structure
PAGE_DIRS = os.environ.get("WIKI_PAGE_DIRS", "concepts,entities,comparisons").split(",")


def api_post(path, data):
    url = f"{MAGMA_API}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def parse_frontmatter(content):
    """Extract YAML frontmatter fields."""
    m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).split("\n"):
        kv = re.match(r'^(\w+):\s*(.+)$', line.strip())
        if kv:
            fm[kv.group(1)] = kv.group(2).strip()
    return fm


def extract_wikilinks(content):
    """Extract [[wikilinks]] from page body."""
    return list(set(
        link.split("|")[0].split("#")[0]
        for link in re.findall(r'\[\[([^\]]+)\]\]', content)
    ))


def ingest_page(rel_path, content):
    """Send one wiki page to MAGMA as an entity event."""
    fm = parse_frontmatter(content)
    wikilinks = extract_wikilinks(content)

    title = fm.get("title", Path(rel_path).stem)
    page_type = fm.get("type", "unknown")
    tags = fm.get("tags", "")

    meta = {
        "source": "obsidian-wiki",
        "wiki_path": rel_path,
        "page_type": page_type,
        "tags": tags,
        "wikilinks": wikilinks[:20],
        "created": fm.get("created", ""),
        "confidence": fm.get("confidence", "unknown"),
    }

    body = re.sub(r'---.*?---', '', content, flags=re.DOTALL).strip()
    summary = body[:500]

    result = api_post("/events", {
        "content": f"[{page_type.upper()}] {title}: {summary}",
        "metadata": meta,
        "session_id": "wiki-ingest",
    })
    return result.get("node_id", "?")


def main():
    total = 0
    for d in PAGE_DIRS:
        dpath = WIKI / d.strip()
        if not dpath.exists():
            print(f"  [skip] directory not found: {dpath}")
            continue
        for f in dpath.glob("*.md"):
            rel = str(f.relative_to(WIKI)).replace("\\", "/")
            content = f.read_text(encoding="utf-8")
            try:
                nid = ingest_page(rel, content)
                total += 1
                if total <= 5 or total % 10 == 0:
                    print(f"  [{total}] {rel} -> {nid[:8]}")
            except Exception as e:
                print(f"  [ERR] {rel}: {e}")

    print(f"\n[OK] Ingested {total} wiki pages into MAGMA")


if __name__ == "__main__":
    main()
