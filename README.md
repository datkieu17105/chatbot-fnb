# Chatbot F&B AI

Chatbot tư vấn F&B cho Nguyễn Sơn Bakery. Project minh họa cách xây dựng chatbot tiếng Việt có dữ liệu nội bộ, retrieval, workflow dạng graph, frontend demo và tùy chọn gọi Gemini khi có API key.

Chatbot vẫn chạy được khi không có API key. Khi đó hệ thống dùng chế độ local-grounded, trả lời dựa trên dữ liệu sản phẩm/chính sách và rule có sẵn.

## Tính năng

- Chat tiếng Việt với khách hàng.
- Tư vấn sản phẩm, giá, nhóm bánh, ảnh sản phẩm.
- Trả lời về giao hàng, thanh toán, đặt trước, đổi trả và thông tin liên hệ.
- Từ chối các câu hỏi ngoài phạm vi cửa hàng bằng giọng nhân viên, không lộ thông tin kỹ thuật.
- Hiển thị card ảnh sản phẩm khi câu trả lời nhắc tới sản phẩm.
- Workflow theo hướng LangGraph; nếu chưa cài được LangGraph thì tự fallback sang local graph.
- Backend Python thuần dùng `http.server`, frontend HTML/CSS/JS tĩnh.

## Cấu trúc

```text
ChatbotF&B/
|-- backend/
|   |-- app/
|   |   |-- server.py
|   |   |-- prompts/
|   |   |   `-- bakery_system_prompt.txt
|   |   `-- chatbot/
|   |       |-- state.py
|   |       |-- nodes.py
|   |       |-- graph.py
|   |       `-- engine.py
|   |-- data/
|   |   |-- raw/nguyenson/
|   |   `-- processed/store-data.json
|   |-- scripts/
|   |   |-- crawl_nguyenson.py
|   |   |-- clean_products.py
|   |   `-- build_site_data.py
|   |-- .env.example
|   `-- server.py
|-- frontend/
|   |-- index.html
|   |-- app.js
|   `-- styles.css
|-- .env.example
|-- requirements.txt
`-- README.md
```

## Yêu cầu

- Python 3.10 trở lên.
- Trình duyệt hiện đại.
- Gemini API key nếu muốn chatbot gọi model Gemini. Không bắt buộc.

## Cài đặt

Clone repo và vào thư mục project:

```bash
git clone https://github.com/datkieu17105/chatbot-fnb.git
cd chatbot-fnb
```

Tạo virtual environment:

```bash
python -m venv .venv
```

Kích hoạt virtual environment:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Cài dependencies:

```bash
pip install -r requirements.txt
```

## Cấu hình môi trường

Backend đọc cấu hình từ file `backend/.env`.

Tạo file env từ file mẫu:

```bash
# Windows PowerShell
Copy-Item backend/.env.example backend/.env

# macOS/Linux
cp backend/.env.example backend/.env
```

Sau đó mở `backend/.env` và điền API key nếu có:

```env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=45
CHATBOT_SCOPE_MODE=strict_bakery
```

Ý nghĩa cấu hình:

- `GEMINI_API_KEY`: API key để gọi Gemini. Có thể để trống nếu chỉ chạy local-grounded.
- `GEMINI_MODEL`: model Gemini sử dụng.
- `GEMINI_TIMEOUT_SECONDS`: thời gian chờ request model.
- `CHATBOT_SCOPE_MODE`: phạm vi trả lời. Khuyến nghị dùng `strict_bakery`.

File `.env` chứa thông tin riêng tư và đã được ignore, không nên commit lên GitHub.

## Chạy project

Chạy server:

```bash
python backend/server.py
```

Mở trình duyệt:

```text
http://127.0.0.1:8000
```

Nếu port `8000` đang bận:

```bash
python backend/server.py --port 8001
```

Sau đó mở:

```text
http://127.0.0.1:8001
```

Không nên mở trực tiếp `frontend/index.html` bằng file URL, vì frontend cần gọi API backend. Hãy mở qua URL do server cung cấp.

## Chạy không cần Gemini API key

Nếu không cấu hình `GEMINI_API_KEY`, chatbot vẫn hoạt động ở chế độ local-grounded:

- Dùng dữ liệu trong `backend/data/processed/store-data.json`.
- Dùng rule/retrieval nội bộ để trả lời.
- Vẫn tư vấn sản phẩm, chính sách, đặt trước, chuyển khoản và ảnh sản phẩm.

Kiểm tra trạng thái:

```text
http://127.0.0.1:8000/api/health
```

Nếu `apiConfigured` là `false`, backend đang chạy không có API key.

## API

Health check:

```http
GET /api/health
```

Chat:

```http
POST /api/chat
Content-Type: application/json

{
  "message": "Cho mình xem ảnh bánh croissant",
  "history": []
}
```

Response chính:

- `answer`: câu trả lời cho khách.
- `scope`: loại câu trả lời, ví dụ `grounded`, `partial`, `out_of_scope`, `general`.
- `sources`: nguồn dữ liệu backend dùng để tạo câu trả lời.
- `attachments`: ảnh sản phẩm để frontend hiển thị.
- `usedModel`: nhánh xử lý hoặc model được dùng.

Frontend hiện không hiển thị các metadata kỹ thuật này cho người dùng cuối.

## Build lại dữ liệu

Build lại knowledge base từ dữ liệu raw:

```bash
python backend/scripts/build_site_data.py
```

Output:

```text
backend/data/processed/store-data.json
```

Crawl lại dữ liệu từ website rồi build:

```bash
python backend/scripts/crawl_nguyenson.py
python backend/scripts/clean_products.py
python backend/scripts/build_site_data.py
```

## Câu hỏi demo

- `Có bánh nào dưới 50k không?`
- `Các món được yêu thích`
- `Ở đây có những loại croissant nào?`
- `Cho mình xem ảnh bánh croissant`
- `Cho mình xem vài loại cookies nhé`
- `Mình chuyển khoản được không?`
- `Cửa hàng có nhận đặt trước không?`
- `Shop giao hàng như thế nào?`
- `Cửa hàng mở cửa lúc mấy giờ?`
- `Thời tiết hôm nay như thế nào?`

## Ghi chú

Đây là project thực hành, không phải chatbot chính thức của Nguyễn Sơn Bakery. Mục tiêu là minh họa cách xây chatbot có dữ liệu nền, retrieval, workflow dạng graph, fallback local và giao diện demo hoàn chỉnh.
