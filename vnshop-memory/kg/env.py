"""Đọc file .env ở thư mục vnshop-memory vào biến môi trường.

Định dạng KEY=VALUE mỗi dòng, dòng bắt đầu bằng # là chú thích; đúng định dạng file
thông tin kết nối mà Neo4j Aura cho tải về. Biến đã đặt sẵn trong PowerShell được ưu tiên.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path=ENV_FILE):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value
