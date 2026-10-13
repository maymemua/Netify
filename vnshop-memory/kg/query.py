"""Truy vấn graph VNSHOP trong Neo4j, thay cho query_vnshop.py.

    python -m kg.query "luồng tạo đơn trả hàng NCC"

Khác bản cũ:
- Tìm bằng fulltext index có bỏ dấu (gõ có dấu hay không dấu đều khớp),
  bỏ từ dừng tiếng Việt, xếp hạng theo điểm Lucene thay vì đếm chuỗi con.
- Đọc đúng tên quan hệ (bản cũ in "connects" cho ~60% cạnh).
- Giữ cạnh trùng cặp (bản cũ dùng nx.Graph nên bị ghi đè).
- Kèm module và file nguồn của từng kết quả.
"""

import os
import re
import sys

from .env import load_env
from . import schema_map as sm

STOPWORDS = {sm.fold(w) for w in (
    "là của và các những cho có không được trong với thì nào gì ở khi như thế "
    "này đó một bị để ra vào lại cũng đã sẽ đang hay hoặc nếu mà về từ theo "
    "nhé ạ ơi sao bao nhiêu"
).split()}

_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def build_fulltext_query(question):
    """Câu hỏi tự nhiên -> chuỗi truy vấn Lucene an toàn.

    Cụm từ đầy đủ được ưu tiên (boost) hơn từng từ lẻ.
    """
    tokens = [t for t in re.findall(r"\w+", question.lower()) if sm.fold(t) not in STOPWORDS]
    if not tokens:
        return None
    escaped = [_LUCENE_SPECIAL.sub(r"\\\1", t) for t in tokens]
    parts = [" OR ".join(escaped)]
    if len(escaped) > 1:
        parts.insert(0, '"{}"^4'.format(" ".join(escaped)))
    return " OR ".join(parts)


SEARCH = f"""
CALL db.index.fulltext.queryNodes('entity_text', $q) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $k
OPTIONAL MATCH (node)-[:FROM_DOC]->(d:SourceDoc)
OPTIONAL MATCH (d)-[:IN_MODULE]->(m:Module)
RETURN node.id AS id, node.name AS name, node.raw_type AS raw_type,
       [l IN labels(node) WHERE l <> '{sm.BASE_LABEL}'][0] AS label,
       node.description AS description, node.community AS community,
       score, d.path AS source_file, m.name AS module
"""

NEIGHBORS = f"""
MATCH (a:{sm.BASE_LABEL})-[r]-(b:{sm.BASE_LABEL})
WHERE a.id IN $ids
WITH a, r, b, [i IN range(0, size($ids) - 1) WHERE $ids[i] = a.id][0] AS rank
RETURN a.id AS a_id, startNode(r) = a AS outgoing, type(r) AS rel, r.notes AS notes,
       r.source_files AS source_files, b.id AS b_id, b.name AS b_name,
       [l IN labels(b) WHERE l <> '{sm.BASE_LABEL}'][0] AS b_label
ORDER BY rank, rel
LIMIT $limit
"""


def run_query(session, question, k=5, edge_limit=30):
    q = build_fulltext_query(question)
    if not q:
        return [], []
    hits = [dict(r) for r in session.run(SEARCH, q=q, k=k)]
    if not hits:
        return [], []
    edges = [dict(r) for r in session.run(NEIGHBORS, ids=[h["id"] for h in hits], limit=edge_limit)]
    return hits, edges


def format_result(hits, edges):
    if not hits:
        return "Không tìm thấy node phù hợp."
    names = {h["id"]: h["name"] for h in hits}
    lines = ["## Node khớp nhất"]
    for i, h in enumerate(hits, 1):
        where = f" — {h['module']}" if h.get("module") else ""
        lines.append(f"{i}. [{h['label']}] {h['name']}{where} (điểm {h['score']:.2f})")
        if h.get("description"):
            lines.append(f"   {h['description']}")
    lines.append("\n## Quan hệ")
    for e in edges:
        a = names.get(e["a_id"], e["a_id"])
        arrow = f"-[{e['rel']}]->" if e["outgoing"] else f"<-[{e['rel']}]-"
        note = f"  ({'; '.join(e['notes'])})" if e.get("notes") else ""
        lines.append(f"- {a} {arrow} [{e['b_label']}] {e['b_name']}{note}")
    files = []
    for h in hits:
        if h.get("source_file") and h["source_file"] not in files:
            files.append(h["source_file"])
    for e in edges:
        for f in e.get("source_files") or []:
            if f not in files:
                files.append(f)
    lines.append("\n## Source Files")
    lines.extend(f"- {f}" for f in files[:8])
    if not files:
        lines.append("- (không có)")
    return "\n".join(lines)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('Cách dùng: python -m kg.query "câu hỏi"', file=sys.stderr)
        return 2
    load_env()
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI")
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri or not password:
        print("Thiếu NEO4J_URI hoặc NEO4J_PASSWORD.", file=sys.stderr)
        return 2
    auth = (os.environ.get("NEO4J_USERNAME", "neo4j"), password)
    with GraphDatabase.driver(uri, auth=auth) as driver:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            hits, edges = run_query(session, " ".join(argv))
    print(format_result(hits, edges))
    return 0


if __name__ == "__main__":
    sys.exit(main())
