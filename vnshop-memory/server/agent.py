"""Agent hỏi đáp nghiệp vụ VNSHOP trên graph Neo4j.

Hai chế độ:
- "claude": Claude tự gọi tool tra graph rồi trả lời (cần ANTHROPIC_API_KEY).
- "search": không dùng LLM, chỉ tìm node khớp nhất và trình bày quan hệ (giống /vnshop-query).

run_chat() là async generator, phát ra các sự kiện cho SSE:
  token {text} · tool_call {id, name, input} · tool_result {id, name, ok, summary, duration_ms}
  graph {ids} · done {conversation_id, trace_id} · error {message}
"""

import json
import os
import time

from . import tools as T

MODEL = os.environ.get("VNSHOP_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("VNSHOP_EFFORT", "medium")
MAX_STEPS = 10

# Giữ cố định: thay đổi system prompt hay danh sách tool giữa các lượt sẽ làm mất
# prompt cache và làm thinking block của các lượt trước không còn hợp lệ.
SYSTEM_PROMPT = """Bạn là trợ lý nghiệp vụ cho dự án VNSHOP (BO Admin, BO NCC, chính sách). \
Tri thức nằm trong một knowledge graph trích từ tài liệu SRS: màn hình, chức năng, trạng thái, \
báo cáo, đơn hàng, NCC, kho, khuyến mãi... và quan hệ giữa chúng.

Cách làm việc:
- Tra graph bằng tool trước khi trả lời; không trả lời nghiệp vụ VNSHOP từ hiểu biết chung.
- Bắt đầu bằng search_entities, sau đó get_entity cho các node liên quan nhất; dùng screen_flow \
khi câu hỏi về luồng màn hình, module_overview khi câu hỏi theo module.
- Trường notes trên quan hệ thường là điều kiện hoặc quy tắc nghiệp vụ, hãy dùng chúng.
- Nếu graph không đủ thông tin, nói rõ phần nào chưa tìm thấy thay vì đoán.

Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc. Cuối câu trả lời, liệt kê các file SRS nguồn \
(source_file) đã dùng dưới tiêu đề "Nguồn"."""


def chat_mode():
    forced = os.environ.get("VNSHOP_CHAT_MODE")
    if forced in ("claude", "search"):
        return forced
    has_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    return "claude" if has_key else "search"


def _step(seq, name, args, ok, started, summary, touched):
    return {"seq": seq, "name": name, "input_json": json.dumps(args, ensure_ascii=False),
            "ok": ok, "duration_ms": int((time.monotonic() - started) * 1000),
            "summary": summary, "touched": touched}


async def _call_tool(db, seq, block_id, name, args, steps):
    """Chạy một tool, trả về (sự kiện, tool_result block, ids, kết quả hoặc None nếu lỗi)."""
    started = time.monotonic()
    error = T.validate_input(name, args)
    if error:
        steps.append(_step(seq, name, args, False, started, error, []))
        return ({"type": "tool_result", "id": block_id, "name": name, "ok": False, "summary": error,
                 "duration_ms": steps[-1]["duration_ms"]},
                {"type": "tool_result", "tool_use_id": block_id, "is_error": True, "content": error}, [], None)
    try:
        result, touched = await T.run_tool(db, name, args)
    except Exception as exc:  # lỗi Neo4j hoặc lỗi dữ liệu: báo lại cho model, không làm hỏng lượt chat
        msg = f"Lỗi khi chạy tool: {exc}"
        steps.append(_step(seq, name, args, False, started, msg, []))
        return ({"type": "tool_result", "id": block_id, "name": name, "ok": False, "summary": msg,
                 "duration_ms": steps[-1]["duration_ms"]},
                {"type": "tool_result", "tool_use_id": block_id, "is_error": True, "content": msg}, [], None)
    summary = T.summarize(name, result)
    steps.append(_step(seq, name, args, "error" not in result, started, summary, touched))
    return ({"type": "tool_result", "id": block_id, "name": name, "ok": "error" not in result,
             "summary": summary, "duration_ms": steps[-1]["duration_ms"]},
            {"type": "tool_result", "tool_use_id": block_id,
             "content": json.dumps(result, ensure_ascii=False, default=str)},
            touched, result)


async def run_chat(db, question, conversation_id=None, client=None):
    started = time.monotonic()
    mode = chat_mode() if client is None else "claude"
    conv = await db.get_conversation(conversation_id) if conversation_id else None
    history = conv["api_messages"] if conv else []
    steps = []
    try:
        if mode == "claude":
            gen = _claude_turn(db, question, history, steps, client)
        else:
            gen = _search_turn(db, question, steps)
        answer, api_messages = "", history
        async for event in gen:
            if event["type"] == "_final":
                answer, api_messages = event["answer"], event.get("api_messages", history)
            else:
                yield event
    except Exception as exc:
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
        return
    if answer is None:  # bị từ chối: không lưu lượt này
        return
    conv_id, trace_id = await db.save_turn(conversation_id, question, answer, api_messages, {
        "mode": mode, "model": MODEL if mode == "claude" else None,
        "duration_ms": int((time.monotonic() - started) * 1000), "steps": steps})
    yield {"type": "done", "conversation_id": conv_id, "trace_id": trace_id}


async def _claude_turn(db, question, history, steps, client):
    import anthropic

    client = client or anthropic.AsyncAnthropic()
    tools = [{**t, "eager_input_streaming": True} for t in T.TOOLS]
    messages = list(history)  # chỉ nối thêm, không sửa lượt cũ
    prompt = question
    similar = await db.similar_questions(question)
    if similar:
        hints = "\n".join(f"- \"{s['question']}\": {'; '.join(s['steps'][:4])}" for s in similar)
        prompt += f"\n\n(Ngữ cảnh: các câu hỏi tương tự trước đây đã tra như sau:\n{hints})"
    messages.append({"role": "user", "content": prompt})
    answer_parts = []
    seq = 0
    for _ in range(MAX_STEPS):
        async with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    answer_parts.append(event.text)
                    yield {"type": "token", "text": event.text}
            response = await stream.get_final_message()

        if response.stop_reason == "refusal":
            yield {"type": "error", "message": "Yêu cầu bị từ chối bởi bộ lọc an toàn. Hãy diễn đạt lại câu hỏi."}
            yield {"type": "_final", "answer": None, "api_messages": history}
            return
        messages.append({"role": "assistant", "content": [b.to_dict() for b in response.content]})
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            break
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Câu trả lời bị cắt do vượt max_tokens khi đang gọi tool")

        results, touched = [], []
        for block in tool_uses:
            seq += 1
            yield {"type": "tool_call", "id": block.id, "name": block.name, "input": block.input}
            event, result_block, ids, _ = await _call_tool(db, seq, block.id, block.name, block.input, steps)
            results.append(result_block)
            touched.extend(ids)
            yield event
        if touched:
            yield {"type": "graph", "ids": list(dict.fromkeys(touched))}
        # Mọi tool_result của một lượt phải nằm chung một user message.
        messages.append({"role": "user", "content": results})
    else:
        answer_parts.append("\n\n_(Dừng vì đã gọi tool quá nhiều lần.)_")

    yield {"type": "_final", "answer": "".join(answer_parts), "api_messages": messages}


async def _search_turn(db, question, steps):
    """Không có LLM: tìm node khớp, mở chi tiết node đầu, trình bày như /vnshop-query."""
    yield {"type": "tool_call", "id": "s1", "name": "search_entities", "input": {"query": question}}
    event, _, hit_ids, found = await _call_tool(db, 1, "s1", "search_entities", {"query": question, "limit": 5}, steps)
    yield event
    hits = (found or {}).get("results", [])
    if not hits:
        text = ("Không tìm thấy node nào khớp. Thử từ khoá khác (tên màn hình, chức năng, "
                "trạng thái...).\n\n_Chế độ tra cứu (chưa cấu hình Claude)._")
        yield {"type": "token", "text": text}
        yield {"type": "_final", "answer": text}
        return

    top = hits[0]
    yield {"type": "tool_call", "id": "s2", "name": "get_entity", "input": {"id": top["id"]}}
    event, _, ent_ids, ent = await _call_tool(db, 2, "s2", "get_entity", {"id": top["id"]}, steps)
    yield event
    yield {"type": "graph", "ids": list(dict.fromkeys(hit_ids + ent_ids))}
    if ent is None or "error" in ent:
        raise RuntimeError(event["summary"])

    lines = [f"**{ent['name']}** ({ent['label']}" + (f", module {ent['module']}" if ent.get("module") else "") + ")"]
    if ent.get("description"):
        lines.append(ent["description"])
    if ent["relations"]:
        lines.append("\n**Quan hệ**")
        for r in ent["relations"][:20]:
            arrow = f"→ {r['rel']} →" if r["outgoing"] else f"← {r['rel']} ←"
            note = f" _({'; '.join(r['notes'])})_" if r.get("notes") else ""
            lines.append(f"- {arrow} [{r['label']}] {r['name']}{note}")
    if len(hits) > 1:
        lines.append("\n**Node khác cũng khớp**")
        lines.extend(f"- [{h['label']}] {h['name']}" for h in hits[1:])
    files = []
    for f in [ent.get("source_file")] + [x for r in ent["relations"] for x in (r.get("source_files") or [])]:
        if f and f not in files:
            files.append(f)
    if files:
        lines.append("\n**Nguồn**")
        lines.extend(f"- `{f}`" for f in files[:6])
    lines.append("\n_Chế độ tra cứu (chưa cấu hình Claude): kết quả lấy thẳng từ graph, không có AI tổng hợp._")
    text = "\n".join(lines)
    yield {"type": "token", "text": text}
    yield {"type": "_final", "answer": text}
