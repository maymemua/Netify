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
kg/docs.py, kg/load_docs.py   làm sạch, cắt đoạn và nạp văn bản SRS (docs_md)
data/graph.sample.json   56 node mẫu đã ẩn danh, dùng cho test
data/docs_md.sample/     2 file SRS giả lập, dùng cho test
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
5. Nạp tài liệu SRS (`docs_md`). Chạy thử trước, không gửi gì đi:
   ```powershell
   python -m kg.load_docs --docs "$G\docs_md" --graph "$G\graph.json" --dry-run
   ```
   Kết quả cho biết số file, số đoạn, số ảnh, token Confluence (`atl_token`) và email đã bỏ/che,
   và `graph_source_files_found_in_docs`: số file nguồn trong graph tìm thấy trong `docs_md`
   (nên gần bằng `graph_source_files`; nếu thấp hẳn là đường dẫn bị lệch, gửi kết quả cho tôi).
   Rồi nạp thật:
   ```powershell
   python -m kg.load_docs --docs "$G\docs_md" --wipe
   ```
   Chỉ phần chữ được gửi lên: ảnh bị bỏ, `atl_token` và email bị che. Mỗi mục (H1–H4) thành một đoạn
   (`:Chunk`, tối đa 2.000 ký tự), nối với file nguồn và với node có tên xuất hiện trong đoạn.
6. Truy vấn thử:
   ```powershell
   python -m kg.query "luồng tạo đơn trả hàng NCC"
   ```

Khi SRS thay đổi: chạy lại pipeline cũ (`pdf_to_md.py` → … → `graph.json`), rồi bước 4 và 5.

## Chạy giao diện web

Sau khi đã nạp (bước 4–5 ở trên), vẫn trong PowerShell với 3 biến `NEO4J_*`:

```powershell
python -m uvicorn server.main:app --port 8000
```

Mở http://localhost:8000.

- **Không có API key**: chạy ở *chế độ tra cứu*: tìm node khớp nhất, trình bày quan hệ và
  trích đoạn SRS, giống `/vnshop-query` nhưng có đồ thị. Không tốn tiền, không gửi dữ liệu ra ngoài.
- **Gemini** (mặc định khi có key): tạo key ở [Google AI Studio](https://aistudio.google.com/apikey),
  đặt `$env:GEMINI_API_KEY = "..."` rồi chạy lại. Gemini tự gọi các tool (`search_entities`,
  `search_docs`, `get_entity`, `screen_flow`, `module_overview`) và viết câu trả lời có trích nguồn SRS.
  Model mặc định `gemini-3.1-pro-preview`, vì Gemini 3.0 Pro (`gemini-3-pro-preview`) đã bị Google tắt
  từ 03/2026. Đổi model bằng `VNSHOP_GEMINI_MODEL`, ví dụ `gemini-3-flash-preview` (rẻ và nhanh hơn).
  Tên model của Google đổi khá nhanh: nếu báo lỗi 404, xem danh sách model hiện hành trong AI Studio.
- **Claude** (tuỳ chọn): đặt `$env:ANTHROPIC_API_KEY`. Model `claude-opus-5-5`;
  đổi bằng `VNSHOP_CLAUDE_MODEL`, `VNSHOP_CLAUDE_EFFORT`. Nếu có cả hai key, Gemini được dùng.
- Có thể ép chế độ bằng `VNSHOP_CHAT_MODE` = `gemini`, `claude` hoặc `search`.

**Dữ liệu gửi đi:** khi bật AI, nội dung các node và đoạn SRS mà AI tra được gửi tới Google (hoặc Anthropic).
Theo điều khoản của Google, dữ liệu gửi qua gói **miễn phí** của Gemini API có thể được dùng để cải thiện
sản phẩm của họ; với tài liệu nội bộ, hãy dùng key thuộc project **có bật thanh toán**
(và tự kiểm tra lại điều khoản hiện hành).

Giao diện có:
- **Chat**: mỗi câu trả lời kèm danh sách bước đã tra (tool, tham số, thời gian).
- **Đồ thị**: các node vừa được tra hiện ngay; bấm để xem chi tiết, bấm đúp để mở rộng hàng xóm;
  ô tìm kiếm để vẽ node bất kỳ; bấm một module ở cột trái để vẽ cả module.
- **Chi tiết node**: loại, module, file SRS, thuộc tính gốc, đoạn SRS nhắc tới node, toàn bộ quan hệ kèm ghi chú điều kiện.
- **Vết suy luận**: từng bước agent đã làm cho một câu trả lời và các node đã chạm tới.
- Hội thoại được lưu trong Neo4j, mở lại từ cột trái.

**Không có đăng nhập.** Máy chủ chỉ nghe ở `127.0.0.1`; đừng mở ra mạng ngoài khi chưa thêm xác thực.

### Ba loại memory (như neo4j-agent-memory)

| Loại | Trong Neo4j |
|---|---|
| Long-term (tri thức) | graph nghiệp vụ do `kg.load` nạp + đoạn SRS `(:Chunk)` do `kg.load_docs` nạp |
| Short-term (hội thoại) | `(:Conversation)-[:HAS_MESSAGE]->(:Message)`; lịch sử gửi model chỉ nối thêm, không sửa (đổi Gemini ↔ Claude thì bắt đầu lịch sử mới) |
| Reasoning (suy luận) | `(:Message)-[:HAS_TRACE]->(:ReasoningTrace)-[:HAS_STEP]->(:ToolCall)-[:TOUCHED]->(:Entity)` |

Câu hỏi mới giống câu cũ (≥ 2 từ trùng) được kèm gợi ý "lần trước đã tra thế nào" cho model.
Chưa dùng thư viện `neo4j-agent-memory`: thư viện này cần thêm model embedding,
mà graph hiện chưa có embedding; mô hình dữ liệu ở trên giữ cùng ý tưởng để chuyển sang sau.

## Mô hình đồ thị trong Neo4j

```
(:Entity:Screen|Function|Status|Report|...) -[:NAVIGATES_TO|DISPLAYS|CONTAINS|...]-> (:Entity:...)
(:Entity) -[:FROM_DOC]-> (:SourceDoc {path}) -[:IN_MODULE]-> (:Module {key, code, name})
(:Entity) -[:IN_GROUP]-> (:Group)          ← hyperedge của graph gốc
(:Chunk {heading, text}) -[:PART_OF]-> (:SourceDoc);  (:Chunk) -[:MENTIONS]-> (:Entity)
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

Đã xác nhận: `tt` = thanh toán (`Payment`), `kh` = khách hàng (`Customer`), `hd` = hoá đơn (`Invoice`).

- `entity` → `BusinessObject` (vì `Entity` là label chung của mọi node).
- Các quan hệ tiếng Việt ngoài 4 cái đã thấy trong báo cáo ("gọi API", "kiểm tra quy tắc",
  "có trạng thái", "kích hoạt") là đoán trước; xem `RELATION_VI_MAP`.

## Bước tiếp theo

1. Tìm theo ý nghĩa (embedding đa ngữ) cho đoạn SRS, bổ sung cho tìm theo từ khoá hiện tại.
2. Thêm đăng nhập nếu muốn chia sẻ cho người khác dùng; deploy (backend + Neo4j Aura).
3. Bộ câu hỏi kiểm thử 20–30 câu có đáp án để đo chất lượng trả lời.

Thư viện trong `web/vendor/`: Cytoscape.js 3.30.2 (MIT), marked 12.0.2 (MIT), DOMPurify 3.1.6 (Apache-2.0/MPL-2.0).
