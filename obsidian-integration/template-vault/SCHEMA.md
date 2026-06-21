# MAGMA Knowledge Schema

## Page Types

| Type | Purpose | Location |
|------|---------|----------|
| `concept` | Curated knowledge page | `concepts/` |
| `raw` | Raw source material | `raw/` |
| `entity` | Named entity (person, project, tool) | `entities/` |
| `comparison` | Side-by-side analysis | `comparisons/` |
| `review` | MAGMA slow path review note | `magma/reviews/` |
| `magma-node` | Exported MAGMA event node | `magma/graph/nodes/` |

## Frontmatter Convention

```yaml
---
title: "Page Title"
type: concept
tags: [tag1, tag2]
created: 2026-01-01
updated: 2026-06-21
confidence: high
---
```

## Linking

Always use `[[wikilinks]]` for cross-references. MAGMA uses these to build entity relationships.
