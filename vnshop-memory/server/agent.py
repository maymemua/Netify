"""Agent hỏi đáp nghiệp vụ VNSHOP trên graph Neo4j.

Ba chế độ:
- "gemini": Gemini tự gọi tool tra graph rồi trả lời (cần GEMINI_API_KEY hoặc GOOGLE_API_KEY).
- "claude": như trên với Claude (cần ANTHROPIC_API_KEY).
- "search": không dùng LLM, chỉ tìm node khớp nhất và trình bày quan hệ (giống /vnshop-query).

run_chat() là async generator, phát ra các sự kiện cho SSE:
  token {text} · tool_call {id, name, input} · tool_result {id, name, ok, summary, duration_ms}
  graph {ids} · done {conversation_id, trace_id} · error {message}
"""

import json
import os
import time

from . import tools as T

CLAUDE_MODEL = os.environ.get("VNSHOP_CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.environ.get("VNSHOP_CLAUDE_EFFORT", "medium")
# Flash có hạn mức miễn phí; Pro (gemini-3.1-pro-preview) chỉ dùng được khi project đã bật thanh toán.
GEMINI_MODEL = os.environ.get("VNSHOP_GEMINI_MODEL", "gemini-3-flash-preview")
MAX_STEPS = 10

# Model hiện trong ô chọn trên giao diện. Thêm/bớt bằng VNSHOP_GEMINI_MODELS / VNSHOP_CLAUDE_MODELS
# (danh sách cách nhau bởi dấu phẩy, lấy đúng tên model trong AI Studio / Anthropic Console).
GEMINI_CHOICES = {
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite (nhanh, hạn mức miễn phí cao)",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro (cần bật thanh toán)",
}
CLAUDE_CHOICES = {
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
}

# Giữ cố định: thay đổi system prompt hay danh sách tool giữa các lượt sẽ làm mất
# prompt cache và làm thinking block của các lượt trước không còn hợp lệ.
SYSTEM_PROMPT = """Bạn là trợ lý nghiệp vụ cho dự án VNSHOP (BO Admin, BO NCC, chính sách). \
Tri thức gồm một knowledge graph trích từ tài liệu SRS (màn hình, chức năng, trạng thái, \
báo cáo, đơn hàng, NCC, kho, khuyến mãi... và quan hệ giữa chúng) và chính văn bản SRS, \
được cắt thành từng đoạn theo tiêu đề.

Cách làm việc:
- Tra graph bằng tool trước khi trả lời; không trả lời nghiệp vụ VNSHOP từ hiểu biết chung.
- Bắt đầu bằng search_entities, sau đó get_entity cho các node liên quan nhất; dùng screen_flow \
khi câu hỏi về luồng màn hình, module_overview khi câu hỏi theo module.
- Dùng search_docs để lấy chi tiết từ văn bản SRS (trường dữ liệu, quy tắc, thông báo lỗi) và \
trích dẫn đúng câu chữ khi cần.
- Đường dẫn tài liệu cho biết loại: docs_md/bo_admin, bo_ncc, srs_fe là SRS (đặc tả đã chốt); \
docs_md/prd là PRD (yêu cầu sản phẩm, có thể là bản nháp); docs_md/api_job là đặc tả API và job. \
Khi các nguồn mâu thuẫn, ưu tiên SRS và nói rõ chỗ khác nhau.
- Trường notes trên quan hệ thường là điều kiện hoặc quy tắc nghiệp vụ, hãy dùng chúng.
- Khi cần nhiều thông tin độc lập, gọi nhiều tool trong CÙNG một lượt (ví dụ search_entities và \
search_docs cùng lúc, hoặc get_entity cho vài node một lúc) để giảm số lần gọi model.
- Nếu graph không đủ thông tin, nói rõ phần nào chưa tìm thấy thay vì đoán.

Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc. Cuối câu trả lời, liệt kê các file SRS nguồn \
(source_file) đã dùng dưới tiêu đề "Nguồn"."""


def chat_mode():
    forced = os.environ.get("VNSHOP_CHAT_MODE")
    if forced in ("gemini", "claude", "search"):
        return forced
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    return "search"


# Model Gemini mà key thực sự gọi được, lấy từ Google lúc máy chủ khởi động (xem main.py).
_discovered = {}
_SKIP_GEMINI = ("tts", "image", "embedding", "audio", "live", "robotics", "computer-use", "native")


def discover_gemini_models(client=None):
    """Hỏi Google danh sách model sinh văn bản mà key gọi được -> {tên: tên hiển thị}."""
    if client is None:
        from google import genai
        client = genai.Client()
    found = {}
    for m in client.models.list():
        name = (m.name or "").removeprefix("models/")
        if not name.startswith("gemini") or "generateContent" not in (m.supported_actions or []):
            continue
        if any(word in name for word in _SKIP_GEMINI):
            continue
        found[name] = m.display_name or name
    return dict(sorted(found.items(), reverse=True))  # bản mới (số lớn) lên trước


def set_discovered(mode, models):
    _discovered[mode] = dict(models)


def _env_list(name, defaults):
    raw = os.environ.get(name)
    if not raw:
        return dict(defaults)
    return {m.strip(): defaults.get(m.strip(), m.strip()) for m in raw.split(",") if m.strip()}


def available_models():
    """Các lựa chọn cho ô chọn model: [{mode, model, label}], lựa chọn mặc định đứng đầu."""
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    claude_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    options = []
    for mode, enabled, default, choices in (
            ("gemini", gemini_key, GEMINI_MODEL,
             _env_list("VNSHOP_GEMINI_MODELS", _discovered.get("gemini") or GEMINI_CHOICES)),
            ("claude", claude_key, CLAUDE_MODEL, _env_list("VNSHOP_CLAUDE_MODELS", CLAUDE_CHOICES))):
        if not enabled:
            continue
        names = [default] + [m for m in choices if m != default]
        options += [{"mode": mode, "model": m, "label": choices.get(m, m)} for m in names]
    options.append({"mode": "search", "model": None, "label": "Tra cứu (không dùng AI)"})
    default_mode = chat_mode()
    options.sort(key=lambda o: o["mode"] != default_mode)  # sort ổn định: giữ thứ tự trong từng nhóm
    return options


def resolve_choice(mode=None, model=None):
    """Kiểm tra lựa chọn từ giao diện (thiếu thì lấy mặc định). Trả về (mode, model) hoặc ValueError."""
    mode = mode or chat_mode()
    if mode == "search":
        return "search", None
    model = model or model_for(mode)
    if any(o["mode"] == mode and o["model"] == model for o in available_models()):
        return mode, model
    raise ValueError(f"Model không có trong danh sách hoặc chưa có API key: {mode} {model}")


def friendly_error(exc, mode, model=None):
    """Lỗi hay gặp từ API model -> câu tiếng Việt; lỗi khác giữ nguyên để dễ tra."""
    text = str(exc)
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    model = model or model_for(mode)
    hints = [
        ((429,), ("RESOURCE_EXHAUSTED", "rate_limit"),
         "Đã hết hạn mức gọi model {model} (theo phút hoặc theo ngày; xem tại https://ai.dev/rate-limit). "
         "Với key miễn phí: model Pro không được gọi; Gemini 3 Flash chỉ 5 lượt/phút, 20 lượt/ngày. "
         "Hãy chọn model khác ở ô chọn model phía trên (vd Gemini 3.1 Flash Lite, hạn mức miễn phí cao hơn), "
         "hoặc bật thanh toán cho project chứa key."),
        ((401, 403), ("API_KEY_INVALID", "PERMISSION_DENIED", "authentication"),
         "API key không hợp lệ hoặc chưa được cấp quyền cho model {model}. Kiểm tra key trong .env."),
        ((404,), ("NOT_FOUND", "not_found"),
         "Không tìm thấy model {model}: tên model có thể đã đổi. Chọn model khác ở ô chọn phía trên, "
         "hoặc sửa danh sách VNSHOP_GEMINI_MODELS / VNSHOP_CLAUDE_MODELS trong .env."),
    ]
    for codes, markers, message in hints:
        if code in codes or any(m in text for m in markers):
            return message.format(model=model) + f"\n\n(Chi tiết: {type(exc).__name__} {code or ''})"
    return f"{type(exc).__name__}: {text}"


def model_for(mode):
    return {"gemini": GEMINI_MODEL, "claude": CLAUDE_MODEL}.get(mode)


async def _with_hints(db, question):
    """Kèm cách tra của các câu hỏi tương tự trước đây (reasoning memory)."""
    similar = await db.similar_questions(question)
    if not similar:
        return question
    hints = "\n".join(f"- \"{s['question']}\": {'; '.join(s['steps'][:4])}" for s in similar)
    return f"{question}\n\n(Ngữ cảnh: các câu hỏi tương tự trước đây đã tra như sau:\n{hints})"


async def run_chat(db, question, conversation_id=None, client=None, mode=None, model=None):
    started = time.monotonic()
    if client is None:
        try:
            mode, model = resolve_choice(mode, model)
        except ValueError as exc:
            yield {"type": "error", "message": str(exc)}
            return
    elif mode != "search":
        model = model or model_for(mode)  # test truyền client giả
    provider = f"{mode}:{model}" if model else mode
    conv = await db.get_conversation(conversation_id) if conversation_id else None
    # Lịch sử gửi model chỉ dùng lại khi cùng model; đổi model thì bắt đầu lịch sử mới
    # (thinking block / thought signature gắn với model đã tạo ra chúng).
    history = conv["api_messages"] if conv and conv.get("api_provider") == provider else []
    steps = []
    try:
        if mode == "claude":
            gen = _claude_turn(db, question, history, steps, client, model=model)
        elif mode == "gemini":
            from .gemini import gemini_turn
            gen = gemini_turn(db, await _with_hints(db, question), history, steps, client,
                              system_prompt=SYSTEM_PROMPT, model=model, max_steps=MAX_STEPS)
        else:
            gen = _search_turn(db, question, steps)
        answer, api_messages = "", history
        async for event in gen:
            if event["type"] == "_final":
                answer, api_messages = event["answer"], event.get("api_messages", history)
            else:
                yield event
    except Exception as exc:
        yield {"type": "error", "message": friendly_error(exc, mode, model)}
        return
    if answer is None:  # bị từ chối: không lưu lượt này
        return
    conv_id, trace_id = await db.save_turn(conversation_id, question, answer, api_messages, provider, {
        "mode": mode, "model": model,
        "duration_ms": int((time.monotonic() - started) * 1000), "steps": steps})
    yield {"type": "done", "conversation_id": conv_id, "trace_id": trace_id}


async def _claude_turn(db, question, history, steps, client, model=CLAUDE_MODEL):
    import anthropic

    client = client or anthropic.AsyncAnthropic()
    tools = [{**t, "eager_input_streaming": True} for t in T.TOOLS]
    messages = list(history)  # chỉ nối thêm, không sửa lượt cũ
    messages.append({"role": "user", "content": await _with_hints(db, question)})
    answer_parts = []
    seq = 0
    for _ in range(MAX_STEPS):
        # Server-side fallback chỉ có cho Opus/Sonnet/Fable; Haiku không có model dự phòng.
        fallback = {} if "haiku" in model else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        async with client.beta.messages.stream(
            model=model,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": CLAUDE_EFFORT},
            **fallback,
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
            event, result_block, ids, _ = await T.call_tool(db, seq, block.id, block.name, block.input, steps)
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
    event, _, hit_ids, found = await T.call_tool(db, 1, "s1", "search_entities", {"query": question, "limit": 5}, steps)
    yield event
    hits = (found or {}).get("results", [])
    if not hits:
        text = ("Không tìm thấy node nào khớp. Thử từ khoá khác (tên màn hình, chức năng, "
                "trạng thái...).\n\n_Chế độ tra cứu (chưa cấu hình AI)._")
        yield {"type": "token", "text": text}
        yield {"type": "_final", "answer": text}
        return

    top = hits[0]
    yield {"type": "tool_call", "id": "s2", "name": "get_entity", "input": {"id": top["id"]}}
    event, _, ent_ids, ent = await T.call_tool(db, 2, "s2", "get_entity", {"id": top["id"]}, steps)
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
    yield {"type": "tool_call", "id": "s3", "name": "search_docs", "input": {"query": question}}
    event, _, _, docs = await T.call_tool(db, 3, "s3", "search_docs", {"query": question, "limit": 2}, steps)
    yield event
    for d in (docs or {}).get("results", []):
        body = d["text"][len(d["heading"]):].lstrip() if d["heading"] and d["text"].startswith(d["heading"]) else d["text"]
        excerpt = body[:500] + ("…" if len(body) > 500 else "")
        lines.append(f"\n**Trích SRS** — {d['heading'] or d['path']}\n\n> " + excerpt.replace("\n", "\n> "))
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
    lines.append("\n_Chế độ tra cứu (chưa cấu hình AI): kết quả lấy thẳng từ graph và SRS, không có AI tổng hợp._")
    text = "\n".join(lines)
    yield {"type": "token", "text": text}
    yield {"type": "_final", "answer": text}
