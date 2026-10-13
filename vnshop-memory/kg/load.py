"""Nạp graph.json của /vnshop-query vào Neo4j.

Ví dụ:
    python -m kg.load --graph path/to/graph.json --index path/to/graph_index.json --dry-run
    python -m kg.load --graph path/to/graph.json --index path/to/graph_index.json --wipe

Kết nối lấy từ biến môi trường NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD,
NEO4J_DATABASE (mặc định "neo4j").
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from . import schema_map as sm
from .normalize import load_files

BATCH = 500
MANAGED_LABELS = [sm.BASE_LABEL, "SourceDoc", "Module", "Group", "GraphBuild"]

SCHEMA = [
    f"CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:{sm.BASE_LABEL}) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT sourcedoc_path IF NOT EXISTS FOR (d:SourceDoc) REQUIRE d.path IS UNIQUE",
    "CREATE CONSTRAINT module_key IF NOT EXISTS FOR (m:Module) REQUIRE m.key IS UNIQUE",
    "CREATE CONSTRAINT group_id IF NOT EXISTS FOR (g:Group) REQUIRE g.id IS UNIQUE",
    f"CREATE INDEX entity_community IF NOT EXISTS FOR (n:{sm.BASE_LABEL}) ON (n.community)",
    f"CREATE INDEX entity_name_folded IF NOT EXISTS FOR (n:{sm.BASE_LABEL}) ON (n.name_folded)",
    # standard-folding bỏ dấu khi đánh chỉ mục và khi truy vấn, nên "don hang" khớp "đơn hàng".
    f"CREATE FULLTEXT INDEX entity_text IF NOT EXISTS FOR (n:{sm.BASE_LABEL}) "
    "ON EACH [n.name, n.description] "
    "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-folding'}}",
]


def _chunks(items, size=BATCH):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _safe(ident):
    if not sm.SAFE_IDENT.match(ident):
        raise ValueError(f"Tên label/quan hệ không hợp lệ: {ident!r}")
    return ident


def wipe(session):
    for label in MANAGED_LABELS:
        session.run(
            f"MATCH (n:{_safe(label)}) CALL (n) {{ DETACH DELETE n }} IN TRANSACTIONS OF 2000 ROWS"
        ).consume()


def write(session, data, built_at):
    for stmt in SCHEMA:
        session.run(stmt).consume()
    session.run("CALL db.awaitIndexes(300)").consume()

    session.run(
        "UNWIND $rows AS row MERGE (m:Module {key: row.key}) "
        "SET m.area = row.area, m.code = row.code, m.name = row.name",
        rows=data.modules,
    ).consume()
    for rows in _chunks(data.docs):
        session.run(
            "UNWIND $rows AS row MERGE (d:SourceDoc {path: row.path}) "
            "SET d.area = row.area, d.name = row.name, d.module_key = row.module_key "
            "WITH d, row WHERE row.module_key IS NOT NULL "
            "MATCH (m:Module {key: row.module_key}) MERGE (d)-[:IN_MODULE]->(m)",
            rows=rows,
        ).consume()

    by_label = {}
    for node in data.nodes:
        by_label.setdefault(node["label"], []).append(node)
    for label, nodes in by_label.items():
        for rows in _chunks(nodes):
            session.run(
                f"UNWIND $rows AS row MERGE (n:{sm.BASE_LABEL} {{id: row.id}}) "
                f"SET n:{_safe(label)}, n += row {{.*, label: null}} "
                "WITH n, row WHERE row.source_file IS NOT NULL "
                "MATCH (d:SourceDoc {path: row.source_file}) MERGE (n)-[:FROM_DOC]->(d)",
                rows=rows,
            ).consume()

    for rel, items in data.rels.items():
        for rows in _chunks(items):
            session.run(
                f"UNWIND $rows AS row "
                f"MATCH (a:{sm.BASE_LABEL} {{id: row.source}}), (b:{sm.BASE_LABEL} {{id: row.target}}) "
                f"MERGE (a)-[r:{_safe(rel)}]->(b) "
                "SET r += row {.*, source: null, target: null}",
                rows=rows,
            ).consume()

    for rows in _chunks(data.groups):
        session.run(
            "UNWIND $rows AS row MERGE (g:Group {id: row.id}) "
            "SET g.name = row.name, g.description = row.description, "
            "    g.relation = row.relation, g.source_file = row.source_file "
            "WITH g, row UNWIND row.members AS mid "
            f"MATCH (n:{sm.BASE_LABEL} {{id: mid}}) MERGE (n)-[:IN_GROUP]->(g)",
            rows=rows,
        ).consume()

    session.run(
        "MERGE (b:GraphBuild {id: 'current'}) "
        "SET b.built_at = $built_at, b.loaded_at = $loaded_at, b.stats_json = $stats",
        built_at=built_at,
        loaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        stats=json.dumps(data.stats, ensure_ascii=False),
    ).consume()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="đường dẫn graph.json")
    ap.add_argument("--index", help="đường dẫn graph_index.json (để lấy community)")
    ap.add_argument("--built-at", help="ngày build graph (YYYY-MM-DD); mặc định lấy ngày sửa file graph.json")
    ap.add_argument("--dry-run", action="store_true", help="chỉ chuẩn hoá và in thống kê, không ghi Neo4j")
    ap.add_argument("--wipe", action="store_true", help="xoá dữ liệu do script này quản lý trước khi nạp")
    args = ap.parse_args(argv)

    data = load_files(args.graph, args.index)
    print(json.dumps(data.stats, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    built_at = args.built_at or date.fromtimestamp(os.path.getmtime(args.graph)).isoformat()

    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    if not uri or not password:
        print("Thiếu NEO4J_URI hoặc NEO4J_PASSWORD.", file=sys.stderr)
        return 2

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            if args.wipe:
                wipe(session)
            write(session, data, built_at)
            counts = session.run(
                f"MATCH (n:{sm.BASE_LABEL}) WITH count(n) AS nodes "
                f"OPTIONAL MATCH (:{sm.BASE_LABEL})-[r]->(:{sm.BASE_LABEL}) "
                "RETURN nodes, count(r) AS rels"
            ).single()
    print(f"Đã nạp: {counts['nodes']} node, {counts['rels']} quan hệ giữa các node nghiệp vụ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
