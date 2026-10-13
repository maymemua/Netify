"""Điểm vào cho Vercel: mọi đường dẫn được chuyển tới đây (xem vercel.json).

Chạy local vẫn dùng: uvicorn server.main:app
"""

import os
import sys

# Thư mục vnshop-memory (chứa kg/, server/, web/) phải nằm trong sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from server.main import app as _app
except Exception as exc:  # nạp code lỗi (thiếu file/thư viện): hiện lỗi thay vì trang 500 trống
    _error = f"{type(exc).__name__}: {exc}"

    async def _app(scope, receive, send):  # ASGI tối giản
        if scope["type"] != "http":
            return
        body = f"VNSHOP Memory không khởi động được.\n\n{_error}\n".encode()
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})

# Vercel chỉ nhận ra function khi `app` được gán ở cấp module (không nằm trong try/except).
app = _app
