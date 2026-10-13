# VNSHOP Memory

Giao diện kiểu [Lenny's Memory](https://github.com/neo4j-labs/agent-memory/tree/main/examples/lennys-memory)
cho nghiệp vụ VNSHOP: hỏi đáp (chat) + đồ thị tri thức + vết suy luận, chạy trên graph
mà skill `/vnshop-query` đang dùng.

```
kg/schema_map.py   bảng chuẩn hoá type node / tên quan hệ  ← sửa ở đây
kg/normalize.py    đọc graph.json + graph_index.json, chuẩn hoá (không cần Neo4j)
kg/load.py         nạp vào Neo4j (constraint, fulltext index bỏ dấu, module, group)
kg/query.py        truy vấn từ dòng lệnh
server/            backend FastAPI: API, agent Claude, lưu hội thoại + vết suy luận
web/               giao diện (HTML/JS thuần, thư viện để sẵn trong web/vendor, không cần build)
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

## Chạy giao diện web

Sau khi đã nạp graph (bước 4 ở trên), vẫn trong PowerShell với 3 biến `NEO4J_*`:

```powershell
python -m uvicorn server.main:app --port 8000
```

Mở http://localhost:8000.

- **Không có API key**: chạy ở *chế độ tra cứu*: tìm node khớp nhất rồi trình bày quan hệ,
  giống `/vnshop-query` nhưng có đồ thị. Không tốn tiền, không gửi dữ liệu ra ngoài.
- **Có API key Claude**: đặt thêm `$env:ANTHROPIC_API_KEY = "sk-ant-..."` rồi chạy lại.
  Claude tự gọi các tool tra graph (`search_entities`, `get_entity`, `screen_flow`,
  `module_overview`) và viết câu trả lời có trích nguồn SRS. Mặc định dùng model
  `claude-opus-5-5`, mức effort `medium`; đổi bằng `VNSHOP_MODEL`, `VNSHOP_EFFORT`.
  Khi bật, nội dung các node mà Claude tra (tên, mô tả, quan hệ, đường dẫn file) được gửi tới API của Anthropic.
- Có thể ép chế độ bằng `VNSHOP_CHAT_MODE=search` hoặc `claude`.

Giao diện có:
- **Chat**: mỗi câu trả lời kèm danh sách bước đã tra (tool, tham số, thời gian).
- **Đồ thị**: các node vừa được tra hiện ngay; bấm để xem chi tiết, bấm đúp để mở rộng hàng xóm;
  ô tìm kiếm để vẽ node bất kỳ; bấm một module ở cột trái để vẽ cả module.
- **Chi tiết node**: loại, module, file SRS, thuộc tính gốc, toàn bộ quan hệ kèm ghi chú điều kiện.
- **Vết suy luận**: từng bước agent đã làm cho một câu trả lời và các node đã chạm tới.
- Hội thoại được lưu trong Neo4j, mở lại từ cột trái.

**Không có đăng nhập.** Máy chủ chỉ nghe ở `127.0.0.1`; đừng mở ra mạng ngoài khi chưa thêm xác thực.

### Ba loại memory (như neo4j-agent-memory)

| Loại | Trong Neo4j |
|---|---|
| Long-term (tri thức) | graph nghiệp vụ do `kg.load` nạp |
| Short-term (hội thoại) | `(:Conversation)-[:HAS_MESSAGE]->(:Message)`; lịch sử gửi Claude chỉ nối thêm, không sửa |
| Reasoning (suy luận) | `(:Message)-[:HAS_TRACE]->(:ReasoningTrace)-[:HAS_STEP]->(:ToolCall)-[:TOUCHED]->(:Entity)` |

Câu hỏi mới giống câu cũ (≥ 2 từ trùng) được kèm gợi ý "lần trước đã tra thế nào" cho Claude.
Chưa dùng thư viện `neo4j-agent-memory`: thư viện này cần thêm model embedding,
mà graph hiện chưa có embedding; mô hình dữ liệu ở trên giữ cùng ý tưởng để chuyển sang sau.

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
   nối với `SourceDoc`, để câu trả lời dựa trên văn bản SRS gốc chứ không chỉ tên node.
   Trước khi làm phải xoá các chuỗi `atl_token=` trong `docs_md`.
2. Thêm đăng nhập nếu muốn chia sẻ cho người khác dùng; deploy (backend + Neo4j Aura).
3. Bộ câu hỏi kiểm thử 20–30 câu có đáp án để đo chất lượng trả lời.

Thư viện trong `web/vendor/`: Cytoscape.js 3.30.2 (MIT), marked 12.0.2 (MIT), DOMPurify 3.1.6 (Apache-2.0/MPL-2.0).
