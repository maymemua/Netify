# Ideas backlog

Ideas worth keeping. Not planned or committed until the PM moves one into `docs/status.md`.

## 1. Group-chat web app for the PM and AI agents
**Raised by:** PM · **Status:** idea

**Problem:** Antigravity and Claude cannot talk to each other. Today they coordinate through repo
files and GitHub PRs, with the PM relaying messages by hand.

**Idea:** a small message-style web app (one shared chat room, or one room per task) where the PM,
the Antigravity agent and Claude all post and read messages.

**First thoughts (to validate):**
- Messages stored in a small database, shown in a simple chat UI.
- Each agent needs a way to read and post: e.g. an MCP server exposing `read_messages` and
  `post_message` tools, which both Antigravity and Claude can be configured to use.
- An agent only reads the chat when it is running; it does not "listen" between sessions.
  A notification or scheduled check-in would be needed for near-real-time replies.
- Must not replace the repo as the source of truth: decisions still go to `docs/decision-log.md`.
- Compare with the zero-build option first: a GitHub issue used as a shared thread.

**Open questions:** who hosts it, how agents authenticate, how to stop two agents acting on the same
message, and whether it is worth building vs. using GitHub issues.
