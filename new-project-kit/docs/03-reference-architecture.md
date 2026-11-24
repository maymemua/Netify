# Reference architecture (from VNSHOP Memory)

VNSHOP Memory code: `github.com/maymemua/Netify`, folder `vnshop-memory/`.

```
Source docs ──(ingestion pipeline)──▶ Graph database ◀──(fixed queries)── Server + agent ◀── Web UI
                                      ├─ Knowledge:  entities + relations
                                      ├─ Documents:  module → doc → chunk ─MENTIONS→ entity
                                      └─ Memory:     conversation → message → trace → tool call ─TOUCHED→ entity
```

## Design principles to keep
1. **The AI chooses, code executes.** The model picks a tool and its input; the server runs fixed,
   read-only queries. The AI cannot change the data.
2. **Every answer is traceable.** Citations, entity ↔ chunk links and reasoning traces.
3. **Memory lives in the same graph**, so past reasoning can guide similar questions.

## Reuse vs. redo

| Part | VNSHOP file(s) | New project |
|---|---|---|
| Agent loop, tool calling, streaming | `server/agent.py`, `server/gemini.py` | **Reuse** |
| Tool runner and input validation | `server/tools.py` | **Reuse**; rewrite tool list and descriptions |
| Memory model (conversations, traces) | `server/db.py` | **Reuse** |
| Auth (shared password) | `server/auth.py` | Reuse for demo; SSO for a real pilot [TBD] |
| Web UI (chat, graph, trace) | `web/` | **Reuse**, rebrand |
| Deployment (Vercel, Docker) | `api/`, `vercel.json`, `Dockerfile` | Reuse; choose durable database hosting |
| Ontology and type mapping | `kg/schema_map.py`, `kg/normalize.py` | **Redo** from Phase 1 |
| Document chunking and loading | `kg/docs.py`, `kg/load_docs.py` | Redo: add embeddings and entity linking |
| Entity extraction | (external tool) | **New**: our own pipeline |
| System prompt | `server/agent.py` | **Redo** for the new domain |
| Eval set | (none) | **New**, before Phase 4 |

## Open architecture questions
- [TBD] Graph database hosting: managed paid tier, self-hosted, or other?
- [TBD] Vector search: inside the graph database, or a separate store?
- [TBD] LLM provider and plan, given data-handling rules.
