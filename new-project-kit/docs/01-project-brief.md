# Project brief

| | |
|---|---|
| **Owner** | AI Product Manager |
| **Status** | Phase 0: Discovery (not started) |
| **Domain** | [TBD: industry / product] |
| **Target users** | [TBD: e.g. PMs, support, sales, engineers] |

## Problem
[TBD after discovery] People spend time searching scattered documents, or asking the few experts
who know the domain. Answers are slow, inconsistent and hard to verify.

## Goal
Answer domain questions in natural language, **grounded in our own documents**, with sources and a
reasoning trace that users can check.

## Core functions (same as VNSHOP Memory)
1. Chat Q&A over a knowledge graph plus source documents.
2. Citations for every answer; "not found" instead of guessing.
3. Graph view of the entities used in the answer.
4. Reasoning trace: which tools the AI called, with what input and result.
5. Conversation memory, and reuse of past reasoning for similar questions.

## Phases

| Phase | Output | Rough time | Gate (PM approves) |
|---|---|---|---|
| **0. Discovery** | Users, ~30 real questions, data sources, constraints, success metrics | 1 week | Questions and sources agreed |
| **1. Data model** | Ontology (entities, relations, properties, provenance), document model, memory model; validated by hand on 2–3 documents | 1 week | Every key question maps to a path in the graph |
| **2. Ingestion** | Connectors, cleaning and PII handling, chunking, LLM-assisted extraction with human spot-checks, embeddings, incremental updates | 1–2 weeks | Extraction quality checked on a sample |
| **3. Eval baseline** | Golden question set, retrieval recall, first error analysis | 3–4 days | Baseline numbers recorded |
| **4. Agent + UI** | Reuse VNSHOP code; new tools, prompt, citations | 1 week | Eval beats baseline; demo approved |
| **5. Pilot** | Real users, feedback loop, monitoring, cost tracking | ongoing | Go / no-go for wider rollout |

**Method for Phase 1 (competency questions):** list what users need to ask, then design entities and
relations so each question maps to a clear path in the graph. The database follows the questions,
not the other way round.

## Success metrics (draft)

| Metric | How measured | Target |
|---|---|---|
| Answers with valid citations | Code check on every answer | [TBD] |
| Answers fully grounded in cited text | LLM judge, validated against PM labels | [TBD] |
| Correct "not found" on out-of-scope questions | Golden set | 100% |
| Retrieval recall@5 | Golden set with labelled entities | [TBD] |
| Time to answer vs. asking an expert | Pilot survey | [TBD] |

## Lessons from VNSHOP Memory

| VNSHOP weakness | Do this instead |
|---|---|
| Graph came from an outside tool we did not control | Own the extraction pipeline, with our own schema |
| Ontology came from whatever the documents contained | Derive the ontology from users' real questions |
| Keyword search only | Hybrid search: keywords + vectors |
| Chunks linked to entities by exact name match | Proper entity linking during extraction |
| No eval until the end | Golden question set before building the agent |
| Grounding enforced only by prompt | Enforce grounding in code (no answer without a source) |
| Free database instance silently deleted | Durable hosting, plus a one-command rebuild |

## Out of scope (for now)
[TBD: agree with stakeholders]
