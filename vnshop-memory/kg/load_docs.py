"""Nạp nội dung SRS (docs_md/*.md) vào Neo4j thành các đoạn (:Chunk).

    python -m kg.load_docs --docs "C:\\...\\vnshop-graph\\docs_md" --dry-run
    python -m kg.load_docs --docs "C:\\...\\vnshop-graph\\docs_md" --wipe

Nhiều nguồn cùng lúc (mỗi nguồn là một nhóm tài liệu, nạp vào docs_md/<nhóm>/...):
    python -m kg.load_docs --source bo_admin="D:\\moi\\bo-admin" --source policy="C:\\cu\\docs_md\\policy" --wipe
--wipe xoá TẤT CẢ đoạn đã nạp trước đó, nên phải liệt kê đủ mọi nguồn muốn giữ.

Chạy SAU kg.load (cần graph để nối đoạn văn với node). Kết nối lấy từ NEO4J_URI,
NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE như kg.load.

Mô hình:
  (:Chunk {id, path, seq, heading, text})-[:PART_OF]->(:SourceDoc)-[:IN_MODULE]->(:Module)
  (:Chunk)-[:MENTIONS]->(:Entity)   khi đoạn văn nhắc tới tên node cùng file nguồn
"""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, fields

from .docs import DocStats, read_docs
from .load import _chunks
from .normalize import parse_source_path

SCHEMA = [
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT sourcedoc_path IF NOT EXISTS FOR (d:SourceDoc) REQUIRE d.path IS UNIQUE",
    "CREATE CONSTRAINT module_key IF NOT EXISTS FOR (m:Module) REQUIRE m.key IS UNIQUE",
    "CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS FOR (c:Chunk) ON EACH [c.heading, c.text] "
    "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-folding'}}",
]

# Tên node quá ngắn (vd "PO", "Lưu") khớp nhầm rất nhiều nên không dùng để nối MENTIONS.
MIN_NAME_CHARS = 5


def write(session, chunks):
    for stmt in SCHEMA:
        session.run(stmt).consume()
    session.run("CALL db.awaitIndexes(300)").consume()

    docs = {}
    for c in chunks:
        if c["path"] not in docs:
            area, mkey, code, mname = parse_source_path(c["path"])
            docs[c["path"]] = {"path": c["path"], "area": area, "module_key": mkey,
                               "module_code": code, "module_name": mname,
                               "name": c["path"].rsplit("/", 1)[-1][:-3]}
    for rows in _chunks(list(docs.values())):
        session.run(
            "UNWIND $rows AS row MERGE (d:SourceDoc {path: row.path}) "
            "SET d.area = row.area, d.name = row.name, d.module_key = row.module_key "
            "WITH d, row WHERE row.module_key IS NOT NULL "
            "MERGE (m:Module {key: row.module_key}) "
            "ON CREATE SET m.area = row.area, m.code = row.module_code, m.name = row.module_name "
            "MERGE (d)-[:IN_MODULE]->(m)",
            rows=rows).consume()

    for rows in _chunks(chunks, 200):
        session.run(
            "UNWIND $rows AS row MERGE (c:Chunk {id: row.id}) "
            "SET c.path = row.path, c.seq = row.seq, c.heading = row.heading, "
            "    c.text = row.text, c.text_folded = row.text_folded "
            "WITH c, row MATCH (d:SourceDoc {path: row.path}) MERGE (c)-[:PART_OF]->(d)",
            rows=rows).consume()

    # Nối đoạn văn với node của cùng file nguồn khi đoạn nhắc tới tên node.
    session.run(
        "MATCH (d:SourceDoc)<-[:FROM_DOC]-(e:Entity) WHERE size(e.name_folded) >= $min "
        "CALL (d, e) { MATCH (c:Chunk)-[:PART_OF]->(d) WHERE c.text_folded CONTAINS e.name_folded "
        "  MERGE (c)-[:MENTIONS]->(e) } IN TRANSACTIONS OF 1000 ROWS",
        min=MIN_NAME_CHARS).consume()

    return session.run(
        "MATCH (c:Chunk) WITH count(c) AS chunks "
        "OPTIONAL MATCH (:Chunk)-[m:MENTIONS]->() "
        "RETURN chunks, count(m) AS mentions").single()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", help="thư mục docs_md (bên trong có bo_admin, bo_ncc, policy...)")
    ap.add_argument("--source", action="append", default=[], metavar="NHOM=THU_MUC",
                    help="thêm một nhóm tài liệu, vd bo_admin=\"C:\\...\\bo-admin\"; dùng nhiều lần được")
    ap.add_argument("--dry-run", action="store_true", help="chỉ đọc, làm sạch, cắt đoạn và in thống kê")
    ap.add_argument("--graph", help="(tuỳ chọn, cho --dry-run) graph.json để kiểm tra file nguồn có khớp không")
    ap.add_argument("--wipe", action="store_true", help="xoá các đoạn (:Chunk) đã nạp trước khi nạp lại")
    args = ap.parse_args(argv)

    sources = []  # (thư mục, tiền tố đường dẫn)
    if args.docs:
        sources.append((args.docs, "docs_md"))
    for item in args.source:
        area, sep, folder = item.partition("=")
        if not sep or not re.fullmatch(r"[a-z0-9_]+", area):
            print(f"--source phải có dạng nhom=thu_muc (nhóm viết thường, không dấu): {item!r}", file=sys.stderr)
            return 2
        sources.append((folder.strip().strip('"'), f"docs_md/{area}"))
    if not sources:
        print("Cần --docs hoặc ít nhất một --source.", file=sys.stderr)
        return 2
    for folder, _ in sources:
        if not os.path.isdir(folder):
            print(f"Không thấy thư mục {folder}", file=sys.stderr)
            return 2

    chunks, stats = [], DocStats()
    per_source = {}
    for folder, prefix in sources:
        part, part_stats = read_docs(folder, prefix=prefix)
        chunks.extend(part)
        per_source[prefix] = {"files": part_stats.files, "chunks": part_stats.chunks}
        for f in fields(DocStats):
            value = getattr(part_stats, f.name)
            setattr(stats, f.name, getattr(stats, f.name) + value)
    dupes = len(chunks) - len({c["id"] for c in chunks})
    if dupes:
        print(f"Có {dupes} đoạn trùng đường dẫn giữa các nguồn: kiểm tra lại --docs/--source.", file=sys.stderr)
        return 2
    summary = asdict(stats)
    summary["per_source"] = per_source
    summary["empty_files"] = summary["empty_files"][:20]
    summary["avg_chunk_chars"] = round(stats.chars / stats.chunks) if stats.chunks else 0
    summary["modules"] = sorted({parse_source_path(c["path"])[1] or "(không module)" for c in chunks})
    if args.graph:
        from .normalize import load_files

        doc_paths = {c["path"] for c in chunks} | set(stats.empty_files)
        graph_paths = {d["path"] for d in load_files(args.graph).docs}
        missing = sorted(graph_paths - doc_paths)
        summary["graph_source_files"] = len(graph_paths)
        summary["graph_source_files_found_in_docs"] = len(graph_paths & doc_paths)
        summary["graph_source_files_missing_sample"] = missing[:15]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    from neo4j import GraphDatabase

    uri, password = os.environ.get("NEO4J_URI"), os.environ.get("NEO4J_PASSWORD")
    if not uri or not password:
        print("Thiếu NEO4J_URI hoặc NEO4J_PASSWORD.", file=sys.stderr)
        return 2
    auth = (os.environ.get("NEO4J_USERNAME", "neo4j"), password)
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            if args.wipe:
                session.run("MATCH (c:Chunk) CALL (c) { DETACH DELETE c } IN TRANSACTIONS OF 2000 ROWS").consume()
            result = write(session, chunks)
    print(f"Đã nạp: {result['chunks']} đoạn SRS, {result['mentions']} liên kết đoạn → node.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
