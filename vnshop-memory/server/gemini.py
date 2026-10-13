"""Vòng lặp tool-calling với Gemini (SDK google-genai).

Gemini 3 trả về "thought signature" gắn trên các part (đặc biệt là part function_call).
Phải gửi lại nguyên vẹn mọi part của lượt model ở request sau, nếu không API trả lỗi 400.
Vì vậy mọi part nhận được khi stream được giữ đúng thứ tự, không gộp hay bỏ part nào.
"""

import asyncio
import json
import math
import re

from . import tools as T

# Hạn mức theo phút (gói miễn phí chỉ 5–15 lượt/phút): chờ rồi thử lại.
# Hạn mức theo ngày (chờ hàng giờ): báo lỗi luôn.
RATE_LIMIT_RETRIES = 3
MAX_WAIT_SECONDS = 70
_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]([\d.]+)s")


def retry_after(exc):
    """Số giây nên chờ nếu lỗi là vượt hạn mức theo phút; None nếu không nên thử lại."""
    text = str(exc)
    if getattr(exc, "code", None) != 429 and "RESOURCE_EXHAUSTED" not in text:
        return None
    m = _RETRY_DELAY.search(text)
    delay = float(m.group(1)) if m else 15.0
    if delay > MAX_WAIT_SECONDS:
        return None
    return math.ceil(delay) + 1

# Lý do dừng nghĩa là câu trả lời bị chặn hoặc hỏng: báo lỗi và không lưu lượt này.
_BLOCKED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII",
            "MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "LANGUAGE", "OTHER"}


def _config(system_prompt):
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t["name"], description=t["description"],
                                      parameters_json_schema=t["input_schema"])
            for t in T.TOOLS])],
        # Agent tự chạy tool (để stream tiến trình và ghi vết suy luận), không để SDK tự gọi.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


async def gemini_turn(db, prompt, history, steps, client=None, *, system_prompt, model, max_steps):
    from google import genai
    from google.genai import types

    client = client or genai.Client()  # đọc GEMINI_API_KEY / GOOGLE_API_KEY
    config = _config(system_prompt)
    contents = [types.Content.model_validate(c) for c in history]  # chỉ nối thêm
    contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
    answer_parts = []
    seq = 0

    for _ in range(max_steps):
        parts, finish = [], None
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                stream = await client.aio.models.generate_content_stream(
                    model=model, contents=contents, config=config)
                async for chunk in stream:
                    if not chunk.candidates:
                        continue
                    cand = chunk.candidates[0]
                    if cand.finish_reason:
                        fr = cand.finish_reason
                        finish = fr.name if hasattr(fr, "name") else str(fr)
                    for part in (cand.content.parts if cand.content and cand.content.parts else []):
                        parts.append(part)
                        if part.text and not part.thought:
                            answer_parts.append(part.text)
                            yield {"type": "token", "text": part.text}
                break
            except Exception as exc:
                wait = retry_after(exc)
                # Đã nhận một phần câu trả lời thì không thử lại (tránh lặp chữ).
                if parts or wait is None or attempt == RATE_LIMIT_RETRIES:
                    raise
                yield {"type": "status",
                       "text": f"Gemini đang giới hạn số lượt gọi mỗi phút, chờ {wait} giây rồi thử lại…"}
                await asyncio.sleep(wait)

        calls = [p.function_call for p in parts if p.function_call]
        if finish in _BLOCKED or not parts:
            yield {"type": "error", "message": f"Gemini không trả lời (lý do: {finish or 'không có nội dung'}). "
                                               "Hãy diễn đạt lại câu hỏi."}
            yield {"type": "_final", "answer": None}
            return
        if finish == "MAX_TOKENS" and calls:
            raise RuntimeError("Câu trả lời bị cắt do vượt giới hạn token khi đang gọi tool")
        contents.append(types.Content(role="model", parts=parts))
        if not calls:
            break

        responses, touched = [], []
        for call in calls:
            seq += 1
            call_id = call.id or f"call_{seq}"
            args = dict(call.args or {})
            yield {"type": "tool_call", "id": call_id, "name": call.name, "input": args}
            event, result_block, ids, _ = await T.call_tool(db, seq, call_id, call.name, args, steps)
            touched.extend(ids)
            yield event
            payload = ({"error": result_block["content"]} if result_block.get("is_error")
                       else {"result": json.loads(result_block["content"])})
            responses.append(types.Part(function_response=types.FunctionResponse(
                id=call.id, name=call.name, response=payload)))
        if touched:
            yield {"type": "graph", "ids": list(dict.fromkeys(touched))}
        contents.append(types.Content(role="tool", parts=responses))
    else:
        answer_parts.append("\n\n_(Dừng vì đã gọi tool quá nhiều lần.)_")

    yield {"type": "_final", "answer": "".join(answer_parts),
           "api_messages": [c.model_dump(mode="json", exclude_none=True) for c in contents]}
