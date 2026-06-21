# MAGMA × Obsidian Integration Guide

Connect MAGMA memory engine to your Obsidian vault for human review, grounding, and graph visualization.

## Prerequisites

- MAGMA running (`docker compose up` or `python -m uvicorn app:app`)
- Obsidian vault
- `.env` configured with `OBSIDIAN_VAULT_PATH`

## Setup

```bash
# 1. Configure your vault path
echo "OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault" >> .env

# 2. Optional: copy the template vault structure
cp -r obsidian-integration/template-vault/* "$OBSIDIAN_VAULT_PATH/"
```

## Workflows

### 1. Dashboard — live MAGMA stats in Obsidian

```bash
python obsidian-integration/scripts/dashboard.py
```

Creates `magma-dashboard.md` in your vault root. Re-run periodically (cron every 30m) to keep stats fresh.

### 2. Wiki Ingest — feed knowledge base to MAGMA

```bash
python obsidian-integration/scripts/ingest.py
```

Reads `.md` pages from configured `WIKI_PAGE_DIRS` (default: `concepts,entities,comparisons`), extracts frontmatter and wikilinks, and sends them as entity nodes to MAGMA.

Customize which directories to scan:

```env
WIKI_PAGE_DIRS=concepts,entities,comparisons,raw
```

### 3. Review Queue — AI-inferred relations for human confirmation

```bash
python obsidian-integration/scripts/review.py
```

Triggers MAGMA Slow Path (LLM) inference on recent events, then creates Obsidian review notes with checkboxes. Review and confirm/reject in Obsidian.

### 4. Graph Export — MAGMA graph as Obsidian Graph View

```bash
python obsidian-integration/scripts/export.py
```

Exports all MAGMA nodes as individual `.md` files with `[[wikilinks]]`, visitable in Obsidian's Graph View. Creates `magma/graph/` with `graph-index.md`.

## Automation (Hermes Agent)

If using Hermes Agent, register scripts as cron jobs:

```
hermes cron create --name magma-dashboard --schedule "30m" \
  --script obsidian-integration/scripts/dashboard.py --no-agent

hermes cron create --name magma-review --schedule "6h" \
  --script obsidian-integration/scripts/review.py --no-agent
```

## Template Vault Structure

The `template-vault/` directory provides a starting structure:

```
template-vault/
├── SCHEMA.md          # Knowledge organization rules
├── raw/               # Raw ingested data
├── concepts/          # Curated concept pages
└── index.md           # Vault index
```

Adapt to your own vault's structure as needed.
