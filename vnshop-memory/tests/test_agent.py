"""Vòng lặp agent với client Claude giả và DB giả: không cần API key hay Neo4j."""

import asyncio
import unittest
from types import SimpleNamespace

from server import agent


class Block(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


def text_response(text):
    return SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text=text)])


def tool_response(*calls):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[Block(type="thinking", thinking="", signature="sig")]
        + [Block(type="tool_use", id=f"tu_{i}", name=name, input=args) for i, (name, args) in enumerate(calls)])


class FakeStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for b in self.response.content:
                if b.type == "text":
                    yield SimpleNamespace(type="text", text=b.text)
        return gen()

    async def get_final_message(self):
        return self.response


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        # Chụp lại messages tại thời điểm gọi (list sẽ còn bị nối thêm sau đó).
        self.calls.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return FakeStream(self.responses.pop(0))


class FakeDB:
    def __init__(self, history=None, provider=f"claude:{agent.CLAUDE_MODEL}"):
        self.history = history or []
        self.provider = provider
        self.saved = None

    async def get_conversation(self, conv_id):
        return {"api_messages": list(self.history), "api_provider": self.provider} if conv_id else None

    async def similar_questions(self, question):
        return []

    async def search(self, query, limit=8, label=None):
        return [{"id": "screen_1", "name": "Màn hình A", "label": "Screen", "score": 3.14159}]

    async def search_docs(self, query, limit=5, path=None):
        return [{"id": "c1", "path": "docs_md/a.md", "heading": "Màn hình A > Quy tắc",
                 "text": "Chỉ duyệt khi đủ chứng từ.", "score": 1.0, "module": None, "entity_ids": ["screen_1"]}]

    async def entity(self, entity_id):
        if entity_id != "screen_1":
            return None
        return {"id": "screen_1", "name": "Màn hình A", "label": "Screen",
                "relations": [{"id": "status_1", "rel": "UPDATES", "outgoing": True, "name": "Đã duyệt",
                               "label": "Status", "notes": ["khi bấm Duyệt"], "source_files": []}]}

    async def save_turn(self, conv_id, question, answer, api_messages, provider, trace):
        self.saved = dict(conv_id=conv_id, question=question, answer=answer,
                          api_messages=api_messages, provider=provider, trace=trace)
        return conv_id or "conv-new", "trace-1"


def collect(gen):
    async def run():
        return [e async for e in gen]
    return asyncio.run(run())


class ClaudeLoopTest(unittest.TestCase):
    def test_tool_round_then_answer(self):
        client = FakeClient([
            tool_response(("search_entities", {"query": "màn hình A"}),
                          ("get_entity", {"id": "screen_1"})),
            text_response("Màn hình A cập nhật trạng thái."),
        ])
        db = FakeDB()
        events = collect(agent.run_chat(db, "màn hình A làm gì?", client=client, mode="claude"))
        types = [e["type"] for e in events]
        self.assertEqual(types, ["tool_call", "tool_result", "tool_call", "tool_result", "graph", "token", "done"])
        self.assertTrue(all(e["ok"] for e in events if e["type"] == "tool_result"))
        self.assertEqual(events[4]["ids"], ["screen_1", "status_1"])

        # Request gửi Claude: system/tools cố định, thinking adaptive, fallback mặc định.
        first = client.calls[0]
        self.assertEqual(first["model"], agent.CLAUDE_MODEL)
        self.assertEqual(first["thinking"], {"type": "adaptive"})
        self.assertEqual(first["fallbacks"], "default")
        self.assertEqual(first["betas"], ["server-side-fallback-2026-07-01"])
        self.assertTrue(all(t["eager_input_streaming"] for t in first["tools"]))
        self.assertEqual(client.calls[1]["system"], first["system"])
        self.assertEqual(client.calls[1]["tools"], first["tools"])

        # Lịch sử: user, assistant (giữ nguyên thinking + tool_use), MỘT user chứa mọi tool_result, assistant.
        msgs = db.saved["api_messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user", "assistant"])
        self.assertEqual(msgs[1]["content"][0], {"type": "thinking", "thinking": "", "signature": "sig"})
        self.assertEqual([b["tool_use_id"] for b in msgs[2]["content"]], ["tu_0", "tu_1"])
        self.assertEqual(db.saved["answer"], "Màn hình A cập nhật trạng thái.")
        self.assertEqual([s["name"] for s in db.saved["trace"]["steps"]], ["search_entities", "get_entity"])
        self.assertEqual(db.saved["trace"]["mode"], "claude")

    def test_history_is_only_appended(self):
        old = [{"role": "user", "content": "câu cũ"},
               {"role": "assistant", "content": [{"type": "text", "text": "trả lời cũ"}]}]
        client = FakeClient([text_response("ok")])
        db = FakeDB(history=old)
        collect(agent.run_chat(db, "câu mới", conversation_id="c1", client=client, mode="claude"))
        sent = client.calls[0]["messages"]
        self.assertEqual(sent[:2], old)
        self.assertEqual(sent[2], {"role": "user", "content": "câu mới"})
        self.assertEqual(db.saved["api_messages"][:3], sent)

    def test_invalid_tool_input_is_reported_not_run(self):
        client = FakeClient([
            tool_response(("get_entity", {"id": 5}), ("no_such_tool", {})),
            text_response("Xin lỗi."),
        ])
        db = FakeDB()
        events = collect(agent.run_chat(db, "?", client=client, mode="claude"))
        results = [e for e in events if e["type"] == "tool_result"]
        self.assertEqual([r["ok"] for r in results], [False, False])
        sent_results = client.calls[1]["messages"][-1]["content"]
        self.assertTrue(all(r["is_error"] for r in sent_results))

    def test_refusal_is_not_saved(self):
        client = FakeClient([SimpleNamespace(stop_reason="refusal", content=[])])
        db = FakeDB()
        events = collect(agent.run_chat(db, "?", client=client, mode="claude"))
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertIsNone(db.saved)


class ModelChoiceTest(unittest.TestCase):
    def env(self, **values):
        from unittest import mock
        return mock.patch.dict(agent.os.environ, values, clear=True)

    def test_choices_follow_available_keys(self):
        with self.env(GEMINI_API_KEY="x"):
            opts = agent.available_models()
            self.assertEqual(opts[0], {"mode": "gemini", "model": agent.GEMINI_MODEL,
                                       "label": agent.GEMINI_CHOICES[agent.GEMINI_MODEL]})
            self.assertIn("gemini-3.1-flash-lite", [o["model"] for o in opts])
            self.assertEqual(opts[-1]["mode"], "search")
            self.assertNotIn("claude", {o["mode"] for o in opts})
        with self.env():
            self.assertEqual(agent.available_models(), [{"mode": "search", "model": None,
                                                         "label": "Tra cứu (không dùng AI)"}])

    def test_discovered_models_replace_builtin_list(self):
        listing = [SimpleNamespace(name=n, display_name=d, supported_actions=acts) for n, d, acts in [
            ("models/gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", ["generateContent", "countTokens"]),
            ("models/gemini-3-flash-preview", "Gemini 3 Flash Preview", ["generateContent"]),
            ("models/gemini-2.5-flash-preview-tts", "TTS", ["generateContent"]),
            ("models/gemini-embedding-001", "Embedding", ["embedContent"]),
            ("models/imagen-4.0", "Imagen", ["predict"]),
        ]]
        client = SimpleNamespace(models=SimpleNamespace(list=lambda: listing))
        found = agent.discover_gemini_models(client)
        self.assertEqual(list(found), ["gemini-3.1-flash-lite", "gemini-3-flash-preview"])
        try:
            agent.set_discovered("gemini", found)
            with self.env(GEMINI_API_KEY="x"):
                labels = {o["model"]: o["label"] for o in agent.available_models() if o["mode"] == "gemini"}
            self.assertEqual(labels, {"gemini-3-flash-preview": "Gemini 3 Flash Preview",
                                      "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite"})
        finally:
            agent._discovered.clear()

    def test_custom_list_and_validation(self):
        with self.env(GEMINI_API_KEY="x", VNSHOP_GEMINI_MODELS="gemini-9-flash, gemini-3.1-flash-lite"):
            models = [o["model"] for o in agent.available_models() if o["mode"] == "gemini"]
            self.assertEqual(models, [agent.GEMINI_MODEL, "gemini-9-flash", "gemini-3.1-flash-lite"])
            self.assertEqual(agent.resolve_choice("gemini", "gemini-9-flash"), ("gemini", "gemini-9-flash"))
            self.assertEqual(agent.resolve_choice(), ("gemini", agent.GEMINI_MODEL))
            self.assertEqual(agent.resolve_choice("search", "whatever"), ("search", None))
            with self.assertRaises(ValueError):
                agent.resolve_choice("gemini", "not-in-list")
            with self.assertRaises(ValueError):
                agent.resolve_choice("claude", agent.CLAUDE_MODEL)  # chưa có key Anthropic

    def test_switching_model_starts_fresh_history(self):
        old = [{"role": "user", "content": "câu cũ"}, {"role": "assistant", "content": [{"type": "text", "text": "x"}]}]
        client = FakeClient([text_response("ok")])
        db = FakeDB(history=old, provider="claude:claude-opus-5-5")
        collect(agent.run_chat(db, "câu mới", conversation_id="c1", client=client,
                               mode="claude", model="claude-haiku-5-5"))
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertEqual(call["messages"], [{"role": "user", "content": "câu mới"}])
        self.assertNotIn("fallbacks", call)  # Haiku không có server-side fallback
        self.assertEqual(db.saved["provider"], "claude:claude-haiku-5-5")
        self.assertEqual(db.saved["trace"]["model"], "claude-haiku-5-5")

    def test_unknown_model_from_ui_is_rejected(self):
        with self.env(GEMINI_API_KEY="x"):
            db = FakeDB()
            events = collect(agent.run_chat(db, "?", mode="gemini", model="gemini-does-not-exist"))
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertIsNone(db.saved)


class FriendlyErrorTest(unittest.TestCase):
    def test_quota_and_unknown(self):
        class ClientError(Exception):
            code = 429
        msg = agent.friendly_error(ClientError("429 RESOURCE_EXHAUSTED ... free_tier ..."), "gemini")
        self.assertIn("hết hạn mức", msg)
        self.assertIn(agent.GEMINI_MODEL, msg)
        self.assertEqual(agent.friendly_error(ValueError("boom"), "gemini"), "ValueError: boom")


class SearchModeTest(unittest.TestCase):
    def test_search_mode_without_llm(self):
        db = FakeDB()
        old_env = agent.os.environ.get("VNSHOP_CHAT_MODE")
        agent.os.environ["VNSHOP_CHAT_MODE"] = "search"
        try:
            events = collect(agent.run_chat(db, "màn hình A"))
        finally:
            if old_env is None:
                del agent.os.environ["VNSHOP_CHAT_MODE"]
            else:
                agent.os.environ["VNSHOP_CHAT_MODE"] = old_env
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("Màn hình A", db.saved["answer"])
        self.assertIn("Chỉ duyệt khi đủ chứng từ.", db.saved["answer"])
        self.assertEqual(db.saved["api_messages"], [])
        self.assertEqual(db.saved["trace"]["mode"], "search")


class ValidateInputTest(unittest.TestCase):
    def test_validate(self):
        from server.tools import validate_input
        self.assertIsNone(validate_input("search_entities", {"query": "x", "label": "Screen", "limit": 3}))
        self.assertIn("bắt buộc", validate_input("search_entities", {}))
        self.assertIn("một trong", validate_input("search_entities", {"query": "x", "label": "Foo"}))
        self.assertIn("khoảng", validate_input("screen_flow", {"id": "a", "depth": 9}))
        self.assertIn("không hợp lệ", validate_input("get_entity", {"id": "a", "x": 1}))
        self.assertIn("số nguyên", validate_input("search_entities", {"query": "x", "limit": True}))


if __name__ == "__main__":
    unittest.main()
