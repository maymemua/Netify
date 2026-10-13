"""Vòng lặp Gemini chạy qua SDK google-genai thật, với máy chủ Gemini giả trên localhost.

Kiểm tra điều quan trọng nhất: thought signature của part function_call được gửi lại
nguyên vẹn ở request sau, cùng function_response.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from server import agent
from tests.test_agent import FakeDB, collect

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None


def sse(*chunks):
    return "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks).encode()


TOOL_TURN = sse({"candidates": [{"content": {"role": "model", "parts": [
    {"functionCall": {"name": "search_entities", "args": {"query": "màn hình A"}}, "thoughtSignature": "c2lnLTE="},
    {"functionCall": {"name": "get_entity", "args": {"id": "screen_1"}}},
]}, "finishReason": "STOP"}]})

ANSWER_TURN = sse(
    {"candidates": [{"content": {"role": "model", "parts": [{"text": "Màn hình A "}]}}]},
    {"candidates": [{"content": {"role": "model", "parts": [{"text": "cập nhật trạng thái.", "thoughtSignature": "c2lnLTI="}]},
                     "finishReason": "STOP"}]},
)

BLOCKED_TURN = sse({"candidates": [{"finishReason": "SAFETY"}]})


def rate_limited(delay):
    body = json.dumps({"error": {"code": 429, "message": "You exceeded your current quota", "status": "RESOURCE_EXHAUSTED",
                                 "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                              "retryDelay": delay}]}}).encode()
    return (429, "application/json", body)


class MockGemini(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).requests.append({"path": self.path, "body": body})
        out = type(self).responses.pop(0)
        status, ctype = 200, "text/event-stream"
        if isinstance(out, tuple):
            status, ctype, out = out
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@unittest.skipIf(genai is None, "google-genai chưa cài")
class GeminiLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockGemini)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def client(self, *responses):
        MockGemini.responses = list(responses)
        MockGemini.requests = []
        return genai.Client(api_key="test", http_options=types.HttpOptions(
            base_url=f"http://127.0.0.1:{self.server.server_port}"))

    def test_tool_round_returns_signatures(self):
        db = FakeDB()
        events = collect(agent.run_chat(db, "màn hình A làm gì?", client=self.client(TOOL_TURN, ANSWER_TURN),
                                        mode="gemini"))
        self.assertEqual([e["type"] for e in events],
                         ["tool_call", "tool_result", "tool_call", "tool_result", "graph", "token", "token", "done"])

        first, second = MockGemini.requests
        self.assertIn(f"/models/{agent.GEMINI_MODEL}:streamGenerateContent", first["path"])
        decls = first["body"]["tools"][0]["functionDeclarations"]
        self.assertEqual([d["name"] for d in decls], ["search_entities", "search_docs", "get_entity", "screen_flow", "module_overview"])
        self.assertIn("systemInstruction", first["body"])

        # Request thứ hai: lượt model gửi lại nguyên vẹn (kể cả signature), rồi một lượt chứa cả hai function_response.
        model_turn, tool_turn = second["body"]["contents"][1:3]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "c2lnLTE=")
        self.assertEqual(model_turn["parts"][0]["functionCall"]["name"], "search_entities")
        self.assertEqual([p["functionResponse"]["name"] for p in tool_turn["parts"]], ["search_entities", "get_entity"])
        self.assertEqual(tool_turn["parts"][0]["functionResponse"]["response"]["result"]["results"][0]["id"], "screen_1")

        # Lịch sử lưu lại đọc ngược được và giữ signature của câu trả lời cuối.
        saved = db.saved
        self.assertEqual(saved["provider"], "gemini")
        self.assertEqual(saved["answer"], "Màn hình A cập nhật trạng thái.")
        restored = [types.Content.model_validate(c) for c in saved["api_messages"]]
        self.assertEqual(restored[-1].parts[-1].thought_signature, b"sig-2")
        self.assertEqual(saved["trace"]["model"], agent.GEMINI_MODEL)

    def test_next_turn_replays_saved_history(self):
        db = FakeDB()
        collect(agent.run_chat(db, "câu 1", client=self.client(ANSWER_TURN), mode="gemini"))
        db2 = FakeDB(history=db.saved["api_messages"], provider="gemini")
        collect(agent.run_chat(db2, "câu 2", conversation_id="c1", client=self.client(ANSWER_TURN), mode="gemini"))
        contents = MockGemini.requests[0]["body"]["contents"]
        self.assertEqual([c["role"] for c in contents], ["user", "model", "user"])
        self.assertEqual(contents[1]["parts"][-1]["thoughtSignature"], "c2lnLTI=")

    def test_history_from_other_provider_is_not_sent(self):
        db = FakeDB(history=[{"role": "user", "content": "claude cũ"}], provider="claude")
        collect(agent.run_chat(db, "câu mới", conversation_id="c1", client=self.client(ANSWER_TURN), mode="gemini"))
        self.assertEqual(len(MockGemini.requests[0]["body"]["contents"]), 1)

    def test_per_minute_rate_limit_waits_and_retries(self):
        from unittest import mock

        from server import gemini

        db = FakeDB()
        with mock.patch.object(gemini.asyncio, "sleep", new=mock.AsyncMock()) as sleep:
            events = collect(agent.run_chat(db, "câu 1", client=self.client(rate_limited("7s"), ANSWER_TURN),
                                            mode="gemini"))
        self.assertEqual([e["type"] for e in events], ["status", "token", "token", "done"])
        sleep.assert_awaited_once_with(8)
        self.assertEqual(len(MockGemini.requests), 2)
        self.assertEqual(db.saved["answer"], "Màn hình A cập nhật trạng thái.")

    def test_daily_rate_limit_fails_with_readable_message(self):
        db = FakeDB()
        events = collect(agent.run_chat(db, "câu 1", client=self.client(rate_limited("18939s")), mode="gemini"))
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertIn("hết hạn mức", events[0]["message"])
        self.assertEqual(len(MockGemini.requests), 1)
        self.assertIsNone(db.saved)

    def test_blocked_answer_is_not_saved(self):
        db = FakeDB()
        events = collect(agent.run_chat(db, "?", client=self.client(BLOCKED_TURN), mode="gemini"))
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertIn("SAFETY", events[0]["message"])
        self.assertIsNone(db.saved)


if __name__ == "__main__":
    unittest.main()
