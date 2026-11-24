# Data model (draft v0.1)

Two parts:
- **Core model**: the same in any domain. Drafted below; review and adjust.
- **Domain model**: entity types and relations for *our* domain. Blank until Phase 0 gives us the
  real questions (`docs/02-phase0-discovery.md`). Method in section 3.

```
                 ┌─────────── DOMAIN LAYER (TBD from competency questions) ───────────┐
                 │   (:Entity:<Type>) ──[:<RELATION> {chunk_ids, confidence}]──▶ (:Entity:<Type>)   │
                 └───────▲───────────────────────────────────────────────────────────┘
                         │ MENTIONS {confidence, method}
 (:Source) ◀─FROM─ (:Document) ◀─PART_OF─ (:Chunk {text, embedding})
                                                 ▲
 (:Conversation)─HAS_MESSAGE→(:Message)─HAS_TRACE→(:ReasoningTrace)─HAS_STEP→(:ToolCall)─USED→(:Chunk)
                                  └─HAS_FEEDBACK→(:Feedback)                  └─TOUCHED→(:Entity)
```

## 1. Core model

### 1.1 Document layer
| Node | Key properties | Why |
|---|---|---|
| `Source` | `id`, `system` (Confluence, Drive, PDF…), `name`, `url` | Where knowledge comes from; access rules differ per source |
| `Document` | `id`, `title`, `url`, `doc_type`, `status` (draft / approved / deprecated), `version`, `updated_at`, `owner` | Lets answers prefer approved, current documents (VNSHOP only had "SRS vs PRD" by folder) |
| `Chunk` | `id`, `text`, `heading_path`, `seq`, `embedding`, `token_count` | Unit of retrieval and citation |

Relations: `(:Document)-[:FROM]->(:Source)`, `(:Chunk)-[:PART_OF]->(:Document)`,
`(:Document)-[:SUPERSEDES]->(:Document)` for versions.

### 1.2 Entity layer (shape only; types come from section 3)
| Element | Key properties | Change vs. VNSHOP |
|---|---|---|
| `Entity` node + one type label | `id`, `name`, `aliases[]`, `description`, `type` | **New:** `aliases` for entity resolution (abbreviations, other spellings) |
| Domain relation | `chunk_ids[]`, `confidence`, `extracted_by`, `extracted_at`, `reviewed` | **New:** every fact points to the text that supports it |
| `(:Chunk)-[:MENTIONS]->(:Entity)` | `confidence`, `method` (llm / alias-match / human) | VNSHOP used exact name match only; now set during extraction |

**Provenance rule:** no entity or relation without at least one supporting chunk. This makes
"every answer has a source" enforceable in code.

### 1.3 Search
| Index | On | Use |
|---|---|---|
| Fulltext, accent-insensitive | `Entity.name`, `Entity.aliases`, `Entity.description` | Find entities by keyword |
| Fulltext, accent-insensitive | `Chunk.text`, `Chunk.heading_path` | Keyword search in documents |
| Vector | `Chunk.embedding` | Search by meaning ("refund" finds "return money") |

Hybrid search = keyword + vector results merged. VNSHOP had keyword only.

### 1.4 Memory layer (reused from VNSHOP, plus feedback)
| Node | Key properties | Change vs. VNSHOP |
|---|---|---|
| `Conversation`, `Message` | as VNSHOP | — |
| `ReasoningTrace`, `ToolCall` | as VNSHOP | **New:** `(:ToolCall)-[:USED]->(:Chunk)` records which text the answer relied on |
| `Feedback` | `rating` (up / down), `reason`, `correct_answer`, `user`, `created_at` | **New:** user feedback becomes eval data |

## 2. Rules for the whole model
- IDs are stable across re-loads, so re-running the pipeline updates instead of duplicating.
- Deleting or re-loading a document removes its chunks and any facts supported *only* by them.
- Personal data (names, emails, customer data) is masked before loading unless the PM approves.
- The app reads the graph; only the ingestion pipeline writes domain data.

## 3. Domain model: method (fill after Phase 0)
1. **List competency questions** from `docs/02-phase0-discovery.md` (aim for 30).
2. **Group them by type:** lookup ("what is X"), relation ("what does X affect"),
   flow ("steps from A to B"), rule ("when can X happen"), comparison, out-of-scope.
3. **Extract nouns → candidate entity types; verbs → candidate relations.**
   Merge synonyms; keep the list short (start with ≤ 15 types).
4. **Write each question as a graph path,** e.g. `(Feature)-[:REQUIRES]->(Permission)`.
   A question with no path means a missing type or relation, or that the answer lives only in text.
5. **Validate by hand on 2–3 real documents:** extract entities manually, check they fit.
6. **PM approves** → record in `docs/decision-log.md` → Phase 2 builds extraction to this schema.

| Competency question | Type | Graph path or "text only" | Entity types used |
|---|---|---|---|
| [TBD] | | | |

## Open decisions
- [TBD] Graph database and hosting (durable, not a free tier that can be deleted).
- [TBD] Embedding model, given the data-handling rules for company documents.
- [TBD] Who reviews extracted facts, and what sample size.
