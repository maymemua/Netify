# VNSHOP Memory – bước 1: đưa graph của /vnshop-query vào Neo4j

Mục tiêu cuối: một giao diện kiểu [Lenny's Memory](https://github.com/neo4j-labs/agent-memory/tree/main/examples/lennys-memory)
(chat + đồ thị + vết suy luận) cho nghiệp vụ VNSHOP. Thư mục này là **bước 1**:
nạp `graph.json` mà skill `/vnshop-query` đang dùng vào Neo4j, chuẩn hoá schema,
và có CLI truy vấn thay cho `query_vnshop.py`.

```
kg/schema_map.py   bảng chuẩn hoá type node / tên quan hệ  ← sửa ở đây
kg/normalize.py    đọc graph.json + graph_index.json, chuẩn hoá (không cần Neo4j)
kg/load.py         nạp vào Neo4j (constraint, fulltext index bỏ dấu, module, group)
kg/query.py        truy vấn từ dòng lệnh
data/graph.sample.json   56 node mẫu đã ẩn danh, dùng cho test
tests/             python -m unittest discover -s tests -t .
```

## Chạy trên máy Windows (nơi có dữ liệu thật)

Dữ liệu thật **không** đưa lên repo hay cloud. Script chạy ngay trên máy bạn và đẩy thẳng vào Neo4j.

1. Chuẩn bị Neo4j: tạo một instance [Neo4j Aura](https://console.neo4j.io) (gói Free đủ cho ~1.600 node),
   lưu lại URI `neo4j+s://xxxx.databases.neo4j.io` và mật khẩu.
   Hoặc chạy local bằng Docker Desktop: `docker compose up -d`.
2. Cài đặt (PowerShell, trong thư mục `vnshop-memory`):
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Xem thống kê trước, chưa ghi gì:
   ```powershell
   $G = "C:\Users\Admin\vnshop-graph\vnshop-graph"
   python -m kg.load --graph "$G\graph.json" --index "$G\graph_index.json" --dry-run
   ```
   Xem hai mục `unmapped_node_types` và `unmapped_relations`. Mục nào có giá trị
   đáng kể thì bổ sung vào `kg/schema_map.py` rồi chạy lại.
4. Nạp thật:
   ```powershell
   $env:NEO4J_URI = "neo4j+s://xxxx.databases.neo4j.io"
   $env:NEO4J_USERNAME = "neo4j"
   $env:NEO4J_PASSWORD = "<mật khẩu>"
   python -m kg.load --graph "$G\graph.json" --index "$G\graph_index.json" --built-at 2026-05-02 --wipe
   ```
   `--wipe` chỉ xoá các node do script này tạo (`Entity`, `SourceDoc`, `Module`, `Group`, `GraphBuild`).
   Chạy lại sau khi sửa `schema_map.py` thì nên giữ `--wipe` để label cũ không còn sót.
5. Truy vấn:
   ```powershell
   python -m kg.query "luồng tạo đơn trả hàng NCC"
   ```

## Mô hình đồ thị trong Neo4j

```
(:Entity:Screen|Function|Status|Report|...) -[:NAVIGATES_TO|DISPLAYS|CONTAINS|...]-> (:Entity:...)
(:Entity) -[:FROM_DOC]-> (:SourceDoc {path}) -[:IN_MODULE]-> (:Module {key, code, name})
(:Entity) -[:IN_GROUP]-> (:Group)          ← hyperedge của graph gốc
(:GraphBuild {built_at, loaded_at, stats_json})
```

- Node: `id`, `name`, `name_folded`, `raw_type` (type gốc), `description`, `source_file`,
  `community` (lấy từ graph_index.json), `properties_json`.
- Quan hệ: `weight` (số cạnh gốc đã gộp), `raw` (giá trị thô), `notes` (nhãn văn bản tự do),
  `source_files`, `descriptions`, `properties_json`.
- Fulltext index `entity_text` dùng analyzer `standard-folding`: gõ "don hang" vẫn khớp "đơn hàng".

## Đã sửa so với query_vnshop.py

| Vấn đề trong bản cũ | Ở đây |
|---|---|
| ~60% cạnh in "connects" vì chỉ đọc trường `relation` | Lấy tên theo `relation` > `type` > `label`; `label` là văn bản tự do thì lưu vào `notes` |
| `nx.Graph` ghi đè cạnh trùng cặp | Giữ mọi quan hệ khác nhau; cạnh trùng hẳn thì gộp, đếm `weight` |
| Hơn 80 giá trị `type` lộn xộn (screen/Screen/Màn hình BO…) | Gom về ~20 label chuẩn, giữ `raw_type` |
| Tìm bằng chuỗi con, không bỏ dấu, không bỏ từ dừng | Fulltext Lucene có bỏ dấu, bỏ từ dừng tiếng Việt, ưu tiên cả cụm |
| 10 cạnh trỏ tới node không tồn tại | Bỏ qua và đếm trong thống kê |

## Giả định cần bạn xác nhận

- `tt` → `Payment` (đoán là "thanh toán").
- `entity` → `BusinessObject` (vì `Entity` là label chung của mọi node).
- Các quan hệ tiếng Việt ngoài 4 cái đã thấy trong báo cáo ("gọi API", "kiểm tra quy tắc",
  "có trạng thái", "kích hoạt") là đoán trước; xem `RELATION_VI_MAP`.

## Bước tiếp theo

1. Nạp nội dung `docs_md` thành node `Chunk` (chia theo heading) + embedding đa ngữ,
   nối với `SourceDoc`, để agent trả lời dựa trên văn bản gốc chứ không chỉ tên node.
   Trước khi làm phải xoá các chuỗi `atl_token=` trong `docs_md`.
2. Backend FastAPI + PydanticAI + neo4j-agent-memory (short-term, reasoning memory),
   chat qua SSE như Lenny demo.
3. Frontend Next.js + NVL: chat, đồ thị luồng màn hình (`NAVIGATES_TO`), cây module, vết tool, ngày build graph.
