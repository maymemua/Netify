"""Điểm vào cho Vercel: mọi đường dẫn được chuyển tới đây (xem vercel.json).

Chạy local vẫn dùng: uvicorn server.main:app
"""

import os
import sys

# Thư mục vnshop-memory (chứa kg/, server/, web/) phải nằm trong sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.main import app  # noqa: E402,F401
