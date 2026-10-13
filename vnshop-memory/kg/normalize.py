"""Đọc graph.json (+ graph_index.json) và chuẩn hoá thành dữ liệu sẵn để nạp Neo4j.

Không phụ thuộc Neo4j, nên chạy được ở chế độ --dry-run để xem thống kê.
"""

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from . import schema_map as sm

# Trường node đã xử lý riêng; các trường còn lại được giữ nguyên làm thuộc tính.
_NODE_HANDLED = {"id", "label", "type", "description", "source_file", "properties"}
_EDGE_HANDLED = {"source", "target", "relation", "type", "label", "source_file",
                 "description", "properties", "key"}


@dataclass
class Normalized:
    nodes: list = field(default_factory=list)        # dict cho từng node
    rels: dict = field(default_factory=dict)          # REL_TYPE -> list dict
    groups: list = field(default_factory=list)        # hyperedge
    docs: list = field(default_factory=list)          # file nguồn docs_md
    modules: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _clean_path(value):
    if not isinstance(value, str) or not value.strip():
        return None
    path = value.strip().replace("\\", "/")
    return path if path.lower().endswith(".md") else None


def parse_source_path(path):
    """docs_md/<area>/<module>/... -> (area, module_key, module_code, module_name)."""
    parts = PurePosixPath(path).parts
    if parts and parts[0] == "docs_md":
        parts = parts[1:]
    if len(parts) < 2:
        return None, None, None, None
    area = parts[0]
    if len(parts) < 3:
        return area, None, None, None
    folder = parts[1]
    m = re.match(r"^(\d+)", folder)
    code = m.group(1) if m else None
    name = sm.BO_ADMIN_MODULES.get(code) if area == "bo_admin" and code else None
    return area, f"{area}/{folder}", code, name or folder


def _scalar_extras(obj, handled):
    """Giữ các trường phụ kiểu đơn giản (str/int/float/bool) làm thuộc tính Neo4j."""
    out = {}
    for k, v in obj.items():
        if k in handled or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
    return out


def _pick_relation(edge):
    """Chọn tên quan hệ theo thứ tự relation > type > label.

    Trả về (tên chuẩn, ghi chú tự do hoặc None, các giá trị thô).
    """
    raws = {k: edge.get(k) for k in ("relation", "type", "label") if edge.get(k)}
    chosen = None
    for key in ("relation", "type", "label"):
        raw = raws.get(key)
        if raw is None:
            continue
        if key == "type" and sm.fold(raw) in sm.EDGE_TYPE_NOT_RELATION:
            continue
        name = sm.relation_name(raw)
        if name:
            chosen = name
            break
    # `label` không phải tên quan hệ => là văn bản mô tả (điều kiện, ghi chú...).
    note = None
    label = raws.get("label")
    if label and sm.relation_name(label) is None:
        note = str(label)
    return chosen, note, [f"{k}={v}" for k, v in raws.items()]


def normalize(graph, index=None):
    out = Normalized()
    stats = {
        "nodes_in": len(graph.get("nodes", [])),
        "edges_in": len(graph.get("links", graph.get("edges", []))),
        "hyperedges_in": len(graph.get("hyperedges", [])),
    }
    community_of = (index or {}).get("node_to_community", {})

    unmapped_types = Counter()
    label_counts = Counter()
    docs = {}
    modules = {}
    node_ids = set()
    duplicate_ids = 0
    no_source = 0

    def register_doc(path):
        if path in docs:
            return
        area, mkey, code, mname = parse_source_path(path)
        docs[path] = {"path": path, "area": area, "module_key": mkey,
                      "name": PurePosixPath(path).stem}
        if mkey and mkey not in modules:
            modules[mkey] = {"key": mkey, "area": area, "code": code, "name": mname}

    for raw in graph.get("nodes", []):
        nid = raw.get("id")
        if nid is None:
            continue
        nid = str(nid)
        if nid in node_ids:
            duplicate_ids += 1
            continue
        node_ids.add(nid)

        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        raw_type = raw.get("type") or raw.get("file_type")
        label, mapped = sm.node_label(raw_type)
        if not mapped:
            unmapped_types[str(raw_type) if raw_type else "(không có type)"] += 1
        label_counts[label] += 1

        name = str(raw.get("label") or nid)
        description = raw.get("description") or props.get("description")
        source_file = _clean_path(raw.get("source_file")) or _clean_path(props.get("source_file"))
        if source_file:
            register_doc(source_file)
        else:
            no_source += 1

        node = {
            "id": nid,
            "name": name,
            "name_folded": sm.fold(name),
            "label": label,
            "raw_type": None if raw_type is None else str(raw_type),
            "description": description if isinstance(description, str) else None,
            "source_file": source_file,
            "properties_json": json.dumps(props, ensure_ascii=False) if props else None,
            "community": community_of.get(nid),
        }
        for k, v in _scalar_extras(raw, _NODE_HANDLED).items():
            node.setdefault(k, v)
        out.nodes.append(node)

    # Cạnh: gộp cạnh trùng (cùng nguồn, quan hệ, đích) thay vì ghi đè như nx.Graph.
    merged = {}
    dangling = 0
    self_loops = 0
    rel_counts = Counter()
    unmapped_rel = Counter()
    for edge in graph.get("links", graph.get("edges", [])):
        src, tgt = str(edge.get("source")), str(edge.get("target"))
        if src not in node_ids or tgt not in node_ids:
            dangling += 1
            continue
        if src == tgt:
            self_loops += 1
        rel, note, raws = _pick_relation(edge)
        if rel is None:
            rel = sm.FALLBACK_RELATION
            unmapped_rel[" | ".join(raws) or "(trống)"] += 1
        key = (src, rel, tgt)
        item = merged.get(key)
        if item is None:
            item = merged[key] = {"source": src, "target": tgt, "weight": 0, "raw": [],
                                  "notes": [], "source_files": [], "descriptions": [],
                                  "properties_json": []}
        item["weight"] += 1
        for r in raws:
            if r not in item["raw"]:
                item["raw"].append(r)
        if note and note not in item["notes"]:
            item["notes"].append(note)
        sf = _clean_path(edge.get("source_file"))
        eprops = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
        sf = sf or _clean_path(eprops.get("source_file"))
        if sf:
            register_doc(sf)
            if sf not in item["source_files"]:
                item["source_files"].append(sf)
        if isinstance(edge.get("description"), str):
            item["descriptions"].append(edge["description"])
        if eprops:
            item["properties_json"].append(json.dumps(eprops, ensure_ascii=False))
        for k, v in _scalar_extras(edge, _EDGE_HANDLED).items():
            item.setdefault(k, v)

    rels = defaultdict(list)
    for (src, rel, tgt), item in merged.items():
        rels[rel].append(item)
        rel_counts[rel] += 1
    out.rels = dict(rels)

    # Hyperedge -> node :Group, thành viên nối bằng IN_GROUP.
    missing_members = 0
    for h in graph.get("hyperedges", []):
        members = h.get("nodes") or h.get("members") or []
        kept = [str(m) for m in members if str(m) in node_ids]
        missing_members += len(members) - len(kept)
        rel_name = sm.relation_name(h.get("relation")) if h.get("relation") else None
        sf = _clean_path(h.get("source_file"))
        if sf:
            register_doc(sf)
        out.groups.append({
            "id": str(h.get("id")),
            "name": str(h.get("label") or h.get("id")),
            "description": h.get("description") if isinstance(h.get("description"), str) else None,
            "relation": rel_name,
            "source_file": sf,
            "members": kept,
        })

    out.docs = list(docs.values())
    out.modules = list(modules.values())

    stats.update({
        "nodes_out": len(out.nodes),
        "duplicate_node_ids": duplicate_ids,
        "nodes_without_source_file": no_source,
        "nodes_with_community": sum(1 for n in out.nodes if n["community"] is not None),
        "labels": dict(label_counts.most_common()),
        "unmapped_node_types": dict(unmapped_types.most_common()),
        "edges_dangling_skipped": dangling,
        "edges_self_loop": self_loops,
        "relationships_out": sum(rel_counts.values()),
        "relationship_types": dict(rel_counts.most_common()),
        "unmapped_relations": dict(unmapped_rel.most_common(30)),
        "groups": len(out.groups),
        "group_members_missing": missing_members,
        "source_docs": len(out.docs),
        "modules": len(out.modules),
    })
    out.stats = stats
    return out


def load_files(graph_path, index_path=None):
    with open(graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    index = None
    if index_path:
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    return normalize(graph, index)
