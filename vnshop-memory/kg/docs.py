"""Đọc docs_md/*.md, làm sạch và cắt thành đoạn (chunk) theo tiêu đề. Không cần Neo4j.

Làm sạch:
- bỏ ảnh (markdown ![..](..) và thẻ <img>): ảnh chưa dùng, link ảnh lại chứa token Confluence
- che mọi atl_token=... còn sót trong link (token Confluence có thể còn hiệu lực)
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import schema_map as sm

MAX_CHARS = 2000      # độ dài tối đa một đoạn
MIN_BODY_CHARS = 20   # mục chỉ có tiêu đề, không có nội dung thì bỏ

_IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMG_HTML = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATL_TOKEN = re.compile(r"atl_token=[A-Za-z0-9_\-]+")
_HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


@dataclass
class DocStats:
    files: int = 0
    chunks: int = 0
    chars: int = 0
    images_removed: int = 0
    atl_tokens_removed: int = 0
    files_with_email: int = 0
    empty_files: list = field(default_factory=list)


def clean(text, stats=None):
    tokens = len(_ATL_TOKEN.findall(text))  # đếm trên văn bản gốc (phần lớn nằm trong link ảnh)
    images = len(_IMG_MD.findall(text)) + len(_IMG_HTML.findall(text))
    text = _IMG_HTML.sub("", _IMG_MD.sub("", text))
    text = _ATL_TOKEN.sub("atl_token=REDACTED", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if stats:
        stats.images_removed += images
        stats.atl_tokens_removed += tokens
    return text.strip()


def _split_long(body, limit=MAX_CHARS):
    """Cắt phần thân dài theo khối (cách nhau bởi dòng trống); khối quá dài thì cắt theo dòng."""
    pieces, current = [], ""
    blocks = re.split(r"\n\s*\n", body)
    for block in blocks:
        units = [block] if len(block) <= limit else block.split("\n")
        for unit in units:
            sep = "\n\n" if unit is block else "\n"
            if current and len(current) + len(sep) + len(unit) > limit:
                pieces.append(current)
                current = ""
            while len(unit) > limit:  # một dòng cực dài
                pieces.append(unit[:limit])
                unit = unit[limit:]
            current = f"{current}{sep}{unit}" if current else unit
    if current.strip():
        pieces.append(current)
    return pieces


def chunk_markdown(text):
    """Trả về list (đường dẫn tiêu đề, nội dung). Mỗi mục H1–H4 là một đoạn, mục dài bị cắt nhỏ."""
    sections, lines = [], []
    path = [None] * 4  # tiêu đề hiện tại ở từng cấp H1..H4

    def flush():
        body = "\n".join(lines).strip()
        if len(body) >= MIN_BODY_CHARS:
            heading = " > ".join(p for p in path if p)
            for piece in _split_long(body):
                sections.append((heading, piece.strip()))
        lines.clear()

    in_code = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            path[level - 1] = m.group(2).strip()
            path[level:] = [None] * (4 - level)
        else:
            lines.append(line)
    flush()
    return sections


def read_docs(docs_dir, prefix="docs_md"):
    """Duyệt toàn bộ *.md trong docs_dir. Trả về (danh sách chunk, thống kê)."""
    root = Path(docs_dir)
    stats = DocStats()
    chunks = []
    for file in sorted(root.rglob("*.md")):
        rel = f"{prefix}/{file.relative_to(root).as_posix()}"
        raw = file.read_text(encoding="utf-8", errors="replace")
        stats.files += 1
        if _EMAIL.search(raw):
            stats.files_with_email += 1
        sections = chunk_markdown(clean(raw, stats))
        if not sections:
            stats.empty_files.append(rel)
        for seq, (heading, body) in enumerate(sections):
            text = body if not heading else f"{heading}\n\n{body}"
            chunks.append({
                "id": hashlib.sha1(f"{rel}#{seq}".encode()).hexdigest()[:16],
                "path": rel,
                "seq": seq,
                "heading": heading,
                "text": text,
                "text_folded": sm.fold(text),
            })
            stats.chars += len(text)
    stats.chunks = len(chunks)
    return chunks, stats
