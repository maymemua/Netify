# Knowledge Assistant (working title)

An AI assistant that answers questions about our domain knowledge, grounded in a knowledge graph and
the original documents, with citations and a visible reasoning trace.

Successor to the **VNSHOP Memory** pet project; same core function, new domain, built properly
from the start.

## Documents

| File | Purpose | Who updates it |
|---|---|---|
| `AGENTS.md` | Rules for every AI agent, incl. the collaboration protocol (read automatically by Antigravity) | PM |
| `CLAUDE.md` | Points Claude to `AGENTS.md`, so both agents follow the same rules | PM |
| `docs/status.md` | Current phase, next actions, open questions | AI assistant, every session |
| `docs/01-project-brief.md` | Goal, scope, phases, success metrics, lessons learned | PM, with AI drafts |
| `docs/02-phase0-discovery.md` | Discovery template: users, questions, sources, constraints | PM fills in, AI synthesizes |
| `docs/03-reference-architecture.md` | What we reuse from VNSHOP Memory and what we redo | AI assistant |
| `docs/04-data-model.md` | Knowledge graph design: core model (drafted) + domain model (after discovery) | AI assistant, PM approves |
| `docs/decision-log.md` | Every decision, with date and reason | AI assistant, on PM's decision |
| `docs/ideas.md` | Ideas backlog, not yet planned | Anyone |

## How to work with the AI assistant
1. Open this folder as the workspace in Antigravity. It reads `AGENTS.md` automatically.
2. Start each session with: *"Read docs/status.md and continue."*
3. Review its plan before it executes anything large.
4. Approve phase gates yourself; the assistant records them in the decision log.
