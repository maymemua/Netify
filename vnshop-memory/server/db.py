"""Truy cập Neo4j cho backend: tri thức VNSHOP (long-term) + hội thoại và vết suy luận.

Ba loại memory, theo mô hình của neo4j-agent-memory / Lenny's Memory:
- long-term:  graph nghiệp vụ do kg.load nạp (:Entity, :SourceDoc, :Module)
- short-term: (:Conversation)-[:HAS_MESSAGE]->(:Message)
- reasoning:  (:Message)-[:HAS_TRACE]->(:ReasoningTrace)-[:HAS_STEP]->(:ToolCall)-[:TOUCHED]->(:Entity)
"""

import json
import os
import uuid
from datetime import datetime, timezone

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ClientError

from kg import schema_map as sm
from kg.query import SEARCH, build_fulltext_query

B = sm.BASE_LABEL
_LABEL = f"[l IN labels(n) WHERE l <> '{B}'][0]"

MEMORY_SCHEMA = [
    "CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT trace_id IF NOT EXISTS FOR (t:ReasoningTrace) REQUIRE t.id IS UNIQUE",
]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _node_out(n, label):
    props = dict(n)
    return {
        "id": props.get("id"),
        "name": props.get("name"),
        "label": label,
        "raw_type": props.get("raw_type"),
        "description": props.get("description"),
        "source_file": props.get("source_file"),
        "community": props.get("community"),
    }


class GraphDB:
    def __init__(self, uri=None, user=None, password=None, database=None):
        missing = [k for k in ("NEO4J_URI", "NEO4J_PASSWORD") if not os.environ.get(k)]
        if missing and not (uri and password):
            raise RuntimeError(
                f"Thiếu {', '.join(missing)}. Đặt biến môi trường trong PowerShell "
                "hoặc tạo file .env trong thư mục vnshop-memory (xem README).")
        self.driver = AsyncGraphDatabase.driver(
            uri or os.environ["NEO4J_URI"],
            auth=(user or os.environ.get("NEO4J_USERNAME", "neo4j"),
                  password or os.environ["NEO4J_PASSWORD"]),
            notifications_min_severity="OFF",
        )
        self.database = database or os.environ.get("NEO4J_DATABASE", "neo4j")

    async def close(self):
        await self.driver.close()

    async def _read(self, query, **params):
        records, _, _ = await self.driver.execute_query(
            query, params, database_=self.database, routing_="r")
        return [r.data() for r in records]

    async def _write(self, query, **params):
        records, _, _ = await self.driver.execute_query(query, params, database_=self.database)
        return [r.data() for r in records]

    async def init_schema(self):
        for stmt in MEMORY_SCHEMA:
            await self._write(stmt)

    # ---------- long-term: tri thức VNSHOP ----------

    async def info(self):
        rows = await self._read(
            f"OPTIONAL MATCH (b:GraphBuild {{id: 'current'}}) "
            f"CALL () {{ MATCH (n:{B}) RETURN count(n) AS nodes }} "
            f"CALL () {{ MATCH (:{B})-[r]->(:{B}) RETURN count(r) AS rels }} "
            "CALL () { MATCH (c:Chunk) RETURN count(c) AS chunks } "
            "RETURN b.built_at AS built_at, b.loaded_at AS loaded_at, nodes, rels, chunks")
        return rows[0] if rows else {}

    async def search(self, query, limit=8, label=None):
        q = build_fulltext_query(query)
        if not q:
            return []
        hits = await self._read(SEARCH, q=q, k=limit * 3 if label else limit)
        if label:
            hits = [h for h in hits if h["label"] == label][:limit]
        return hits

    async def entity(self, entity_id, limit=40):
        rows = await self._read(
            f"MATCH (n:{B} {{id: $id}}) "
            "OPTIONAL MATCH (n)-[:FROM_DOC]->(d:SourceDoc) "
            "OPTIONAL MATCH (d)-[:IN_MODULE]->(m:Module) "
            f"RETURN n, {_LABEL} AS label, d.path AS source_file, m.name AS module, m.key AS module_key",
            id=entity_id)
        if not rows:
            return None
        row = rows[0]
        out = _node_out(row["n"], row["label"])
        out.update(source_file=row["source_file"] or out["source_file"],
                   module=row["module"], module_key=row["module_key"])
        props_json = row["n"].get("properties_json")
        out["properties"] = json.loads(props_json) if props_json else None
        out["relations"] = await self._read(
            f"MATCH (n:{B} {{id: $id}})-[r]-(b:{B}) "
            "RETURN startNode(r) = n AS outgoing, type(r) AS rel, r.notes AS notes, "
            "r.source_files AS source_files, b.id AS id, b.name AS name, "
            f"[l IN labels(b) WHERE l <> '{B}'][0] AS label "
            "ORDER BY rel, name LIMIT $limit",
            id=entity_id, limit=limit)
        out["chunks"] = await self._read(
            "MATCH (c:Chunk)-[:MENTIONS]->(n {id: $id}) "
            "RETURN c.id AS id, c.path AS path, c.heading AS heading, left(c.text, 600) AS excerpt "
            "ORDER BY c.path, c.seq LIMIT 5",
            id=entity_id)
        out["groups"] = await self._read(
            f"MATCH (n:{B} {{id: $id}})-[:IN_GROUP]->(g:Group) "
            "RETURN g.id AS id, g.name AS name, g.description AS description",
            id=entity_id)
        return out

    async def search_docs(self, query, limit=5, path=None):
        """Tìm đoạn văn SRS (:Chunk) theo từ khoá. None nếu chưa nạp tài liệu (chưa có index)."""
        q = build_fulltext_query(query)
        if not q:
            return []
        try:
            return await self._read(
                "CALL db.index.fulltext.queryNodes('chunk_text', $q) YIELD node AS c, score "
                "WHERE $path IS NULL OR c.path = $path "
                "WITH c, score ORDER BY score DESC LIMIT $limit "
                "OPTIONAL MATCH (c)-[:PART_OF]->(:SourceDoc)-[:IN_MODULE]->(m:Module) "
                f"OPTIONAL MATCH (c)-[:MENTIONS]->(e:{B}) "
                "RETURN c.id AS id, c.path AS path, c.heading AS heading, c.text AS text, "
                "round(score, 2) AS score, m.name AS module, collect(e.id)[..10] AS entity_ids "
                "ORDER BY score DESC",
                q=q, path=path, limit=limit)
        except ClientError as exc:
            if "chunk_text" in str(exc):
                return None
            raise

    async def screen_flow(self, screen_id, direction="out", depth=3, limit=60):
        depth = max(1, min(int(depth), 5))
        pattern = {"out": f"(s)-[:NAVIGATES_TO*1..{depth}]->(t)",
                   "in": f"(s)<-[:NAVIGATES_TO*1..{depth}]-(t)",
                   "both": f"(s)-[:NAVIGATES_TO*1..{depth}]-(t)"}[direction]
        rows = await self._read(
            f"MATCH (s:{B} {{id: $id}}) MATCH p = {pattern} "
            "UNWIND relationships(p) AS r "
            "WITH DISTINCT r LIMIT $limit "
            "RETURN startNode(r).id AS source, startNode(r).name AS source_name, "
            "endNode(r).id AS target, endNode(r).name AS target_name, r.notes AS notes",
            id=screen_id, limit=limit)
        return rows

    async def modules(self):
        return await self._read(
            "MATCH (m:Module) "
            f"OPTIONAL MATCH (m)<-[:IN_MODULE]-(:SourceDoc)<-[:FROM_DOC]-(n:{B}) "
            "RETURN m.key AS key, m.code AS code, m.name AS name, m.area AS area, "
            "count(DISTINCT n) AS entities "
            "ORDER BY m.area, toInteger(coalesce(m.code, '9999')), m.name")

    async def module_entities(self, module_key, label=None, limit=50):
        return await self._read(
            "MATCH (m:Module {key: $key})<-[:IN_MODULE]-(:SourceDoc)<-[:FROM_DOC]-(n:" + B + ") "
            f"WITH DISTINCT n, {_LABEL} AS label WHERE $label IS NULL OR label = $label "
            "RETURN n.id AS id, n.name AS name, label ORDER BY label, name LIMIT $limit",
            key=module_key, label=label, limit=limit)

    async def subgraph(self, ids, expand=True, limit=150):
        """Node + cạnh để vẽ: các node cho trước, thêm hàng xóm 1 bước nếu expand."""
        ids = list(dict.fromkeys(ids))[:60]
        if not ids:
            return {"nodes": [], "edges": []}
        node_rows = await self._read(
            f"MATCH (n:{B}) WHERE n.id IN $ids "
            f"OPTIONAL MATCH (n)-[]-(m:{B}) WHERE $expand "
            "WITH collect(DISTINCT n) + collect(DISTINCT m) AS ns "
            "UNWIND ns AS n WITH DISTINCT n LIMIT $limit "
            f"RETURN n, {_LABEL} AS label",
            ids=ids, expand=expand, limit=limit)
        nodes = [_node_out(r["n"], r["label"]) for r in node_rows]
        node_ids = [n["id"] for n in nodes]
        edges = await self._read(
            f"MATCH (a:{B})-[r]->(b:{B}) WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN elementId(r) AS id, a.id AS source, b.id AS target, type(r) AS rel, "
            "r.notes AS notes LIMIT 600",
            ids=node_ids)
        focus = set(ids)
        for n in nodes:
            n["focus"] = n["id"] in focus
        return {"nodes": nodes, "edges": edges}

    # ---------- short-term: hội thoại ----------

    async def list_conversations(self, limit=50):
        return await self._read(
            "MATCH (c:Conversation) RETURN c.id AS id, c.title AS title, "
            "c.created_at AS created_at, c.updated_at AS updated_at "
            "ORDER BY c.updated_at DESC LIMIT $limit", limit=limit)

    async def get_conversation(self, conv_id):
        rows = await self._read(
            "MATCH (c:Conversation {id: $id}) "
            "OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message) "
            "OPTIONAL MATCH (m)-[:HAS_TRACE]->(t:ReasoningTrace) "
            "WITH c, m, t ORDER BY m.seq "
            "RETURN c.id AS id, c.title AS title, c.api_messages_json AS api_messages_json, "
            "c.api_provider AS api_provider, "
            "collect(CASE WHEN m IS NULL THEN null ELSE "
            "{role: m.role, content: m.content, created_at: m.created_at, trace_id: t.id} END) AS messages",
            id=conv_id)
        if not rows:
            return None
        row = rows[0]
        row["api_messages"] = json.loads(row.pop("api_messages_json") or "[]")
        return row

    async def delete_conversation(self, conv_id):
        await self._write(
            "MATCH (c:Conversation {id: $id}) "
            "OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message) "
            "OPTIONAL MATCH (m)-[:HAS_TRACE]->(t:ReasoningTrace) "
            "OPTIONAL MATCH (t)-[:HAS_STEP]->(s:ToolCall) "
            "DETACH DELETE c, m, t, s", id=conv_id)

    async def save_turn(self, conv_id, question, answer, api_messages, provider, trace):
        """Ghi một lượt hỏi đáp. api_messages là toàn bộ lịch sử gửi model (chỉ nối thêm)."""
        conv_id = conv_id or str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        now = _now()
        await self._write(
            "MERGE (c:Conversation {id: $conv_id}) "
            "ON CREATE SET c.created_at = $now, c.title = $title, c.seq = 0 "
            "SET c.updated_at = $now, c.api_messages_json = $api, c.api_provider = $provider "
            "WITH c "
            "CREATE (u:Message {role: 'user', content: $question, created_at: $now, seq: c.seq + 1}) "
            "CREATE (a:Message {role: 'assistant', content: $answer, created_at: $now, seq: c.seq + 2}) "
            "SET c.seq = c.seq + 2 "
            "CREATE (c)-[:HAS_MESSAGE]->(u), (c)-[:HAS_MESSAGE]->(a) "
            "CREATE (a)-[:HAS_TRACE]->(t:ReasoningTrace {id: $trace_id, question: $question, "
            "  question_folded: $question_folded, "
            "  mode: $mode, model: $model, created_at: $now, duration_ms: $duration_ms}) "
            "WITH t UNWIND $steps AS step "
            "CREATE (t)-[:HAS_STEP]->(s:ToolCall {seq: step.seq, name: step.name, "
            "  input_json: step.input_json, ok: step.ok, duration_ms: step.duration_ms, "
            "  summary: step.summary}) "
            "WITH s, step UNWIND step.touched AS eid "
            f"MATCH (e:{B} {{id: eid}}) MERGE (s)-[:TOUCHED]->(e)",
            conv_id=conv_id, now=now, title=question[:80], api=json.dumps(api_messages, ensure_ascii=False),
            provider=provider,
            question=question, question_folded=sm.fold(question), answer=answer, trace_id=trace_id, mode=trace["mode"],
            model=trace.get("model"), duration_ms=trace["duration_ms"], steps=trace["steps"])
        return conv_id, trace_id

    # ---------- reasoning: vết suy luận ----------

    async def get_trace(self, trace_id):
        rows = await self._read(
            "MATCH (t:ReasoningTrace {id: $id}) "
            "OPTIONAL MATCH (t)-[:HAS_STEP]->(s:ToolCall) "
            f"OPTIONAL MATCH (s)-[:TOUCHED]->(e:{B}) "
            "WITH t, s, collect(e.id) AS touched ORDER BY s.seq "
            "RETURN t {.*} AS trace, collect(CASE WHEN s IS NULL THEN null ELSE "
            "s {.name, .input_json, .ok, .duration_ms, .summary, .seq, touched: touched} END) AS steps",
            id=trace_id)
        if not rows:
            return None
        return {**rows[0]["trace"], "steps": rows[0]["steps"]}

    async def similar_questions(self, question, limit=3):
        """Câu hỏi cũ giống câu hỏi mới (khớp từ không dấu), để agent tham khảo cách đã tra."""
        words = [w for w in sm.fold(question).split() if len(w) > 2]
        if len(words) < 2:
            return []
        return await self._read(
            "MATCH (t:ReasoningTrace)-[:HAS_STEP]->(s:ToolCall) "
            "WITH t, collect(s.name + ' ' + coalesce(s.input_json, '')) AS steps, "
            "  size([w IN $words WHERE t.question_folded CONTAINS w]) AS hit "
            "WHERE hit >= 2 "
            "RETURN t.question AS question, steps ORDER BY hit DESC, t.created_at DESC LIMIT $limit",
            words=words, limit=limit)
