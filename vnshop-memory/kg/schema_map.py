"""Bảng chuẩn hoá schema cho graph.json của /vnshop-query.

graph.json gốc ghi `type` của node và tên quan hệ rất không thống nhất
(hoa/thường, Anh/Việt, nằm ở 3 trường khác nhau). File này gom chúng về một
bộ label/quan hệ chuẩn cho Neo4j. Sửa ở đây khi `load --dry-run` báo
"type chưa map" hoặc "quan hệ chưa map".

Khoá trong các bảng đều đã qua fold(): chữ thường, bỏ dấu, đ -> d,
khoảng trắng/gạch ngang -> một dấu cách, bỏ "_" ở hai đầu.
"""

import re
import unicodedata


def fold(text):
    """Chữ thường, bỏ dấu tiếng Việt, gộp khoảng trắng ("_" và "-" coi như dấu cách)."""
    text = unicodedata.normalize("NFD", str(text))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[\s\-_]+", " ", text)
    return text.strip()


# Label gốc gắn cho mọi node nghiệp vụ, ngoài label chuẩn bên dưới.
BASE_LABEL = "Entity"
FALLBACK_LABEL = "Concept"

# fold(type gốc) -> label chuẩn
NODE_TYPE_MAP = {
    # Màn hình
    "screen": "Screen", "man hinh": "Screen", "man hinh bo": "Screen", "page": "Screen",
    "bo screen": "Screen", "giao dien": "Screen", "ui component": "Screen",
    # Chức năng / tính năng
    "func": "Function", "function": "Function", "chuc nang": "Function", "action": "Function",
    "feature": "Feature", "tinh nang": "Feature",
    # Trạng thái
    "status": "Status", "trang thai": "Status", "state": "Status",
    # Báo cáo, chứng từ
    "report": "Report", "bao cao": "Report",
    "doc": "Document", "document": "Document", "tai lieu": "Document", "chung tu": "Document",
    "tai lieu nghiep vu": "Document", "tai lieu/chung tu": "Document",
    # Đối tượng dữ liệu nghiệp vụ ("entity" trong graph gốc)
    "entity": "BusinessObject",
    # Vai trò, hệ thống
    "role": "Role", "vai tro": "Role", "actor": "Role",
    "sys": "System", "system": "System", "he thong": "System",
    # Miền VNSHOP
    "payment": "Payment", "thanh toan": "Payment",
    "tt": "Payment",  # GIẢ ĐỊNH: tt = thanh toán. Cần xác nhận.
    "km": "Promotion", "khuyen mai": "Promotion", "promotion": "Promotion",
    "sp": "Product", "san pham": "Product", "product": "Product", "product variant": "Product",
    "attribute": "Product", "attributeset": "Product", "brand": "Product",
    "category": "Category", "product category": "Category", "nganh hang": "Category", "danh muc": "Category",
    "inventory": "Inventory", "ton kho": "Inventory",
    "stocktransfer": "BusinessProcess",
    "carrier": "Shipping", "thong tin van chuyen": "Shipping", "van chuyen": "Shipping",
    "kh": "Customer", "khach hang": "Customer", "customer": "Customer",  # GIẢ ĐỊNH: kh = khách hàng
    "api": "System",
    "rule": "BusinessRule", "business logic": "BusinessRule", "logic": "BusinessRule",
    "logic xu ly": "BusinessRule", "quy tac": "BusinessRule",
    "audit log": "Log",
    "mua": "BusinessProcess", "mua hang": "BusinessProcess", "purchase": "BusinessProcess",
    "kho": "Warehouse", "warehouse": "Warehouse",
    "don": "Order", "don hang": "Order", "order": "Order",
    "ncc": "Supplier", "nha cung cap": "Supplier", "supplier": "Supplier",
    "notif": "Notification", "notification": "Notification", "thong bao": "Notification",
    "policy": "Policy", "policy concept": "Policy", "chinh sach": "Policy",
    "log": "Log",
    "nghiep vu": "BusinessProcess", "process": "BusinessProcess",
    "concept": "Concept",
}

# Giá trị xuất hiện trong trường `type` của CẠNH nhưng là phân loại chứ
# không phải tên quan hệ, nên bỏ qua khi chọn tên quan hệ.
EDGE_TYPE_NOT_RELATION = {"phan mem", "software", "nghiep vu"}

# fold(quan hệ tiếng Việt) -> quan hệ chuẩn
RELATION_VI_MAP = {
    "goi api": "CALLS_API",
    "truy cap": "ACCESSES",
    "dang nhap ad": "LOGS_IN_WITH",
    "gui thong tin": "SENDS_TO",
    "cap nhat trang thai": "UPDATES",
    "tao so": "CREATES",
    "tao po": "CREATES",
    "lay hang tu kho": "TAKES_STOCK_FROM",
    "thuc hien": "PERFORMS",
    "kiem tra quy tac": "CHECKS_RULE",
    "co trang thai": "HAS_STATUS",
    "kich hoat": "TRIGGERS",
    "hien thi": "DISPLAYS",
    "chua": "CONTAINS",
    "tao": "CREATES",
    "cap nhat": "UPDATES",
    "yeu cau": "REQUIRES",
    "dieu huong": "NAVIGATES_TO",
}

FALLBACK_RELATION = "RELATED_TO"

# Tên quan hệ tiếng Anh dạng snake_case, ví dụ "navigates_to".
_SNAKE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
# Chỉ những tên khớp mẫu này mới được dùng làm label/relationship type
# trong Cypher (được chèn trực tiếp vào câu lệnh).
SAFE_IDENT = re.compile(r"^[A-Z][A-Za-z0-9_]*$")

# Mã module BO Admin -> tên hiển thị (tên thư mục trong docs_md đã mất dấu).
BO_ADMIN_MODULES = {
    "1": "Đăng nhập", "2": "Sản phẩm", "3": "Tác vụ", "4": "CTKM",
    "5": "Cung ứng", "6": "Đơn hàng", "7": "Phí giao hàng", "8": "Giao dịch hoàn tiền",
    "9": "Giao hàng", "10": "Thông báo", "11": "Báo cáo", "12": "Danh mục",
    "13": "Người dùng", "14": "Khách hàng", "15": "Trang bán hàng", "16": "Cài đặt",
    "17": "Log", "18": "Sự kiện offline", "19": "Đối soát ETON",
}

# Thư mục cấp 1 trong docs_md không chia module -> tên hiển thị.
AREA_NAMES = {"bo_admin": "BO Admin", "bo_ncc": "BO NCC", "policy": "Chính sách", "policies": "Chính sách"}


def node_label(raw_type):
    """Trả về (label chuẩn, đã map hay chưa)."""
    if raw_type is None or not str(raw_type).strip():
        return FALLBACK_LABEL, False
    key = fold(raw_type)
    if key in NODE_TYPE_MAP:
        return NODE_TYPE_MAP[key], True
    return FALLBACK_LABEL, False


def relation_name(raw):
    """Đổi một giá trị thô thành tên quan hệ chuẩn, hoặc None nếu không phải tên quan hệ."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    key = fold(raw)
    if key in RELATION_VI_MAP:
        return RELATION_VI_MAP[key]
    if raw.isascii() and _SNAKE.match(raw.lower()):
        return raw.upper()
    return None
