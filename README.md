# Chatbot F&B AI

Đây là project chatbot F&B sử dụng dữ liệu từ trang web của Nguyễn Sơn Bakery. Chatbot có dữ liệu nội bộ, retrieval, workflow dạng graph, gọi Gemini khi có API key và vẫn chạy được ở chế độ local khi chưa có API key.

## Chức năng chính

- Chat với khách bằng tiếng Việt.
- Tư vấn sản phẩm, giá, loại bánh, chính sách giao hàng, thanh toán, đổi trả và thông tin liên hệ.
- Trả lời dựa trên dữ liệu đã crawl từ website, không chỉ trả lời tự do.
- Hiển thị nguồn tham chiếu và ảnh sản phẩm trong khung chat.
- Có workflow theo hướng LangGraph: chuẩn bị context, route intent, gọi model hoặc fallback local, finalize response.
- Có frontend demo chạy trực tiếp cùng backend.

## Cấu trúc project

```text
ChatbotF&B/
├─ backend/
│  ├─ app/
│  │  ├─ server.py
│  │  ├─ prompts/
│  │  │  └─ bakery_system_prompt.txt
│  │  └─ chatbot/
│  │     ├─ state.py
│  │     ├─ nodes.py
│  │     ├─ graph.py
│  │     └─ engine.py
│  ├─ data/
│  │  ├─ raw/nguyenson/
│  │  └─ processed/store-data.json
│  ├─ scripts/
│  │  ├─ crawl_nguyenson.py
│  │  ├─ clean_products.py
│  │  └─ build_site_data.py
│  ├─ .env.example
│  └─ server.py
├─ frontend/
│  ├─ index.html
│  ├─ app.js
│  └─ styles.css
├─ requirements.txt
└─ README.md
```

## Luồng xử lý chatbot

```text
Người dùng nhập câu hỏi
  -> POST /api/chat
  -> prepare_context: chuẩn hóa câu hỏi, tìm sản phẩm/chính sách phù hợp
  -> route: chọn nhánh xử lý
  -> conversation_guard | scope_guard | local_grounded | local_curated | model_grounded | general
  -> finalize: chuẩn hóa answer, sources, attachments
  -> frontend hiển thị câu trả lời, nguồn và ảnh
```

Các file quan trọng:

- `backend/app/chatbot/state.py`: định nghĩa state cho workflow.
- `backend/app/chatbot/nodes.py`: các node xử lý.
- `backend/app/chatbot/graph.py`: lắp workflow bằng LangGraph nếu đã cài, fallback local graph nếu chưa cài.
- `backend/app/chatbot/engine.py`: load dữ liệu, retrieval, prompt, gọi Gemini, format kết quả.
- `backend/app/server.py`: API server và static server cho frontend.
- `frontend/app.js`: logic chat trên trình duyệt.

## Cách chạy nhanh

Mở PowerShell tại thư mục project:

```powershell
cd "C:\Users\Kieu Doan Dat\VSCode\ChatbotF&B"
```

Tạo virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cài thư viện:

```powershell
pip install -r requirements.txt
```

Chạy server:

```powershell
python backend/server.py
```

Giữ nguyên cửa sổ terminal này trong lúc dùng chatbot. Nếu đóng terminal hoặc nhấn `Ctrl+C`, backend sẽ tắt và frontend sẽ báo `Backend chưa kết nối`.

Mở trình duyệt:

```text
http://127.0.0.1:8000
```

Nếu port 8000 đang bận:

```powershell
python backend/server.py --port 8001
```

Sau đó mở:

```text
http://127.0.0.1:8001
```

Không mở trực tiếp file `frontend/index.html` nếu chưa chắc backend đang chạy. Cách ổn định nhất là luôn mở bằng URL do server in ra, ví dụ `http://127.0.0.1:8000`.

## Chạy không cần API key

Project vẫn chạy nếu chưa có Gemini API key. Khi đó chatbot dùng chế độ `local-grounded`, tức là trả lời dựa trên dữ liệu local và rule/retrieval có sẵn.

Lệnh chạy vẫn là:

```powershell
python backend/server.py
```

## Chạy với Gemini API key

Copy file mẫu:

```powershell
Copy-Item backend\.env.example backend\.env
```

Mở `backend/.env` và điền:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=45
CHATBOT_SCOPE_MODE=strict_bakery
```

Chạy lại server:

```powershell
python backend/server.py
```

Kiểm tra health:

```text
http://127.0.0.1:8000/api/health
```

Nếu `apiConfigured` là `true`, chatbot đã nhận API key.

## Build lại dữ liệu

Khi muốn build lại knowledge base từ dữ liệu raw:

```powershell
python backend/scripts/build_site_data.py
```

Output chính:

```text
backend/data/processed/store-data.json
```

Nếu muốn crawl lại từ website:

```powershell
python backend/scripts/crawl_nguyenson.py
python backend/scripts/clean_products.py
python backend/scripts/build_site_data.py
```

## API

Health:

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

Response chính gồm:

- `answer`: câu trả lời.
- `scope`: loại câu trả lời, ví dụ `grounded`, `partial`, `out_of_scope`, `general`.
- `sources`: nguồn tham chiếu.
- `attachments`: ảnh sản phẩm nếu có.
- `usedModel`: model hoặc nhánh fallback đã dùng.

## Câu hỏi demo

- `Có bánh nào dưới 50k không?`
- `Các món nào được yêu thích?`
- `Cho mình xem ảnh bánh croissant`
- `Cho mình xem vài loại cookies nhé`
- `Shop giao hàng như thế nào?`
- `Mình chuyển khoản được không?`
- `Cửa hàng mở cửa lúc mấy giờ?`
- `Tư vấn cho mình mua điện thoại mới`

## Ghi chú

Đây là project thực hành, không phải chatbot chính thức của Nguyễn Sơn Bakery. Mục tiêu chính là minh họa cách xây chatbot AI có dữ liệu nền, retrieval, nguồn tham chiếu, workflow dạng graph và frontend demo hoàn chỉnh.
