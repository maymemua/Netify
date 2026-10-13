"""Công cụ (tool) agent dùng để tra graph VNSHOP.

Mỗi tool trả về (kết quả dạng dict, danh sách id node đã chạm tới). Danh sách id dùng để
vẽ đồ thị trên giao diện và ghi cạnh :TOUCHED trong vết suy luận.
"""

import json
import time

LABELS = ["Screen", "Function", "Feature", "Status", "Report", "Document", "BusinessObject",
          "Role", "System", "Payment", "Promotion", "Product", "Warehouse", "Order", "Supplier",
          "Notification", "Policy", "Log", "BusinessProcess", "Concept"]

TOOLS = [
    {
        "name": "search_entities",
        "description": (
            "Tìm node trong knowledge graph nghiệp vụ VNSHOP (màn hình, chức năng, trạng thái, "
            "báo cáo, đơn hàng, NCC, khuyến mãi...) theo từ khoá. Gõ có dấu hay không dấu đều được. "
            "Luôn gọi tool này trước để lấy id rồi mới gọi get_entity."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khoá, ví dụ 'đơn trả hàng NCC'"},
                "label": {"type": "string", "enum": LABELS,
                          "description": "Chỉ lấy node thuộc loại này (tuỳ chọn)"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_docs",
        "description": (
            "Tìm đoạn văn gốc trong tài liệu SRS (mô tả màn hình, bảng trường dữ liệu, quy tắc nghiệp vụ, "
            "thông báo lỗi...). Dùng khi cần chi tiết hoặc trích dẫn mà graph không có. "
            "Có thể giới hạn trong một file bằng path (lấy từ source_file của node)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khoá, ví dụ 'điều kiện huỷ đơn trả hàng'"},
                "path": {"type": "string", "description": "Chỉ tìm trong file này (tuỳ chọn)"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_entity",
        "description": (
            "Xem chi tiết một node: mô tả, thuộc tính, module, file SRS nguồn, và toàn bộ quan hệ "
            "(DISPLAYS, CONTAINS, TRIGGERS, UPDATES, REQUIRES, NAVIGATES_TO...) tới node khác, "
            "và vài đoạn SRS nhắc tới node (chunks). "
            "Trường 'notes' trên quan hệ thường chứa điều kiện/quy tắc nghiệp vụ."),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "id lấy từ search_entities"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "screen_flow",
        "description": "Lần theo luồng điều hướng giữa các màn hình (quan hệ NAVIGATES_TO) từ một màn hình.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id màn hình xuất phát"},
                "direction": {"type": "string", "enum": ["out", "in", "both"],
                              "description": "out: đi tới đâu; in: từ đâu tới; both: cả hai"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "module_overview",
        "description": (
            "Không truyền module_key: liệt kê các module SRS (Đơn hàng, Cung ứng, CTKM...). "
            "Có module_key: liệt kê node thuộc module đó, có thể lọc theo loại."),
        "input_schema": {
            "type": "object",
            "properties": {
                "module_key": {"type": "string"},
                "label": {"type": "string", "enum": LABELS},
            },
            "additionalProperties": False,
        },
    },
]

_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


def validate_input(name, args):
    """Kiểm tra input của tool theo schema (kiểu, bắt buộc, enum, khoảng). Trả về lỗi hoặc None."""
    schema = _SCHEMAS.get(name)
    if schema is None:
        return f"Không có tool tên {name!r}"
    if not isinstance(args, dict):
        return "Input phải là object"
    props = schema["properties"]
    for key in schema.get("required", []):
        if key not in args:
            return f"Thiếu trường bắt buộc {key!r}"
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            return f"Trường không hợp lệ {key!r}"
        if spec["type"] == "string" and not isinstance(value, str):
            return f"{key!r} phải là chuỗi"
        if spec["type"] == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"{key!r} phải là số nguyên"
        if "enum" in spec and value not in spec["enum"]:
            return f"{key!r} phải là một trong {spec['enum']}"
        if spec["type"] == "integer" and not (spec.get("minimum", value) <= value <= spec.get("maximum", value)):
            return f"{key!r} ngoài khoảng cho phép"
    return None


async def run_tool(db, name, args):
    if name == "search_entities":
        hits = await db.search(args["query"], limit=args.get("limit", 8), label=args.get("label"))
        for h in hits:
            h["score"] = round(h["score"], 2)
        return {"results": hits}, [h["id"] for h in hits]

    if name == "search_docs":
        found = await db.search_docs(args["query"], limit=args.get("limit", 5), path=args.get("path"))
        if found is None:
            return {"results": [], "note": "Chưa nạp tài liệu SRS (chạy kg.load_docs)."}, []
        return {"results": found}, [i for r in found for i in r["entity_ids"]]

    if name == "get_entity":
        ent = await db.entity(args["id"])
        if ent is None:
            return {"error": f"Không có node id {args['id']!r}"}, []
        return ent, [ent["id"]] + [r["id"] for r in ent["relations"]]

    if name == "screen_flow":
        edges = await db.screen_flow(args["id"], args.get("direction", "out"), args.get("depth", 3))
        ids = {args["id"]}
        for e in edges:
            ids.update((e["source"], e["target"]))
        return {"edges": edges}, sorted(ids)

    if name == "module_overview":
        if not args.get("module_key"):
            return {"modules": await db.modules()}, []
        rows = await db.module_entities(args["module_key"], args.get("label"))
        return {"entities": rows}, [r["id"] for r in rows]

    raise ValueError(f"Không có tool {name!r}")


def summarize(name, result):
    """Một dòng mô tả kết quả, hiện trên thẻ tool ở giao diện."""
    if "error" in result:
        return result["error"]
    if name in ("search_entities", "search_docs"):
        return result.get("note") or f"{len(result['results'])} kết quả"
    if name == "get_entity":
        return f"{result['name']} — {len(result['relations'])} quan hệ"
    if name == "screen_flow":
        return f"{len(result['edges'])} bước điều hướng"
    if name == "module_overview":
        return f"{len(result.get('modules') or result.get('entities') or [])} mục"
    return ""


def _step(seq, name, args, ok, started, summary, touched):
    return {"seq": seq, "name": name, "input_json": json.dumps(args, ensure_ascii=False),
            "ok": ok, "duration_ms": int((time.monotonic() - started) * 1000),
            "summary": summary, "touched": touched}


async def call_tool(db, seq, block_id, name, args, steps):
    """Chạy một tool, trả về (sự kiện, tool_result block, ids, kết quả hoặc None nếu lỗi)."""
    started = time.monotonic()
    error = validate_input(name, args)
    if error:
        steps.append(_step(seq, name, args, False, started, error, []))
        return ({"type": "tool_result", "id": block_id, "name": name, "ok": False, "summary": error,
                 "duration_ms": steps[-1]["duration_ms"]},
                {"type": "tool_result", "tool_use_id": block_id, "is_error": True, "content": error}, [], None)
    try:
        result, touched = await run_tool(db, name, args)
    except Exception as exc:  # lỗi Neo4j hoặc lỗi dữ liệu: báo lại cho model, không làm hỏng lượt chat
        msg = f"Lỗi khi chạy tool: {exc}"
        steps.append(_step(seq, name, args, False, started, msg, []))
        return ({"type": "tool_result", "id": block_id, "name": name, "ok": False, "summary": msg,
                 "duration_ms": steps[-1]["duration_ms"]},
                {"type": "tool_result", "tool_use_id": block_id, "is_error": True, "content": msg}, [], None)
    summary = summarize(name, result)
    steps.append(_step(seq, name, args, "error" not in result, started, summary, touched))
    return ({"type": "tool_result", "id": block_id, "name": name, "ok": "error" not in result,
             "summary": summary, "duration_ms": steps[-1]["duration_ms"]},
            {"type": "tool_result", "tool_use_id": block_id,
             "content": json.dumps(result, ensure_ascii=False, default=str)},
            touched, result)
