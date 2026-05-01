# Chatbot F&B

Demo chatbot hỏi đáp dựa trên dữ liệu được thu thập từ website Nguyễn Sơn Bakery, với kiến trúc tách riêng `frontend/` và `backend/`.

## Cấu trúc

```text
ChatbotF&B/
├─ frontend/
│  ├─ index.html
│  ├─ app.js
│  └─ styles.css
├─ backend/
│  ├─ server.py
│  ├─ chatbot_backend.py
│  ├─ build_site_data.py
│  ├─ bakery_system_prompt.txt
│  ├─ data/
│  └─ output_nguyenson/
└─ README.md
```

## Điểm chính của bài

- Frontend tập trung vào giao diện chat, hiển thị tin nhắn, ô nhập câu hỏi, ảnh sản phẩm và kết quả trả lời.
- Backend xử lý dữ liệu đã crawl, retrieval, prompt, gọi Gemini nếu có API key, fallback local và trả về dữ liệu có nguồn tham chiếu.
- Dữ liệu sản phẩm và chính sách được build từ bộ crawl trong `backend/output_nguyenson/`.
- Nếu nguồn trả về là sản phẩm, frontend có thể hiển thị card sản phẩm và hình ảnh; với nguồn chính sách/liên hệ thì chỉ hiển thị nội dung trả lời để giao diện gọn hơn.

## Cấu hình file .env

Tạo file `.env` trong thư mục `backend/`:

```text
ChatbotF&B/
└─ backend/
   └─ .env
```

Nội dung mẫu:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=45
```

Nếu không có `GEMINI_API_KEY`, hệ thống vẫn chạy ở chế độ `local-grounded`. Chế độ này vẫn trả lời được dựa trên dữ liệu cục bộ, nhưng khả năng hiểu câu hỏi ngoài phạm vi sẽ hạn chế hơn.

Không đưa file `.env` lên GitHub/GitLab vì file này có thể chứa API key. File `.gitignore` đã chặn `.env`, log và cache Python.

## Cách chạy nhanh

1. Cài hoặc kiểm tra Python.
2. Tạo file `backend/.env` nếu muốn dùng Gemini.
3. Build lại dữ liệu nếu cần:

```powershell
python backend/build_site_data.py
```

4. Chạy server:

```powershell
python backend/server.py
```

5. Mở trình duyệt:

```text
http://127.0.0.1:8000
```

Server backend sẽ phục vụ luôn frontend, nên chỉ cần một lệnh chạy để demo đầy đủ.

## API chính

- `GET /api/health`: trả về cấu hình chatbot, số lượng nguồn dữ liệu và thông tin cửa hàng.
- `POST /api/chat`: nhận `message` và `history`, trả về `answer`, `sources`, `attachments`, `scope`, `usedModel`.

## Gợi ý demo khi thuyết trình

- `Các món nào được yêu thích?`
- `Có bánh nào dưới 50k không?`
- `Cho mình xem vài loại cookies nhé`
- `Cho mình xem ảnh bánh croissant`
- `Mình cần đặt bánh trước bao lâu?`
- `Cửa hàng mở cửa lúc mấy giờ?`
- `Tư vấn cho mình mua điện thoại mới, có cấu hình tốt`

## Ghi chú

- Dữ liệu trong project được lấy từ website Nguyễn Sơn Bakery để xây dựng chatbot thử nghiệm, không phải chatbot chính thức của thương hiệu.
- Nếu không có `GEMINI_API_KEY`, hệ thống chạy ở chế độ `local-grounded`.
- Với câu hỏi ngoài phạm vi, chế độ `local-grounded` có thể fallback sang gợi ý sản phẩm thay vì từ chối chính xác. Đây là hạn chế của phiên bản thử nghiệm và có thể cải thiện bằng bước nhận diện câu hỏi ngoài miền.
- Frontend có thể mở riêng, nhưng cách ổn định nhất để nộp bài/demo là chạy qua `python backend/server.py`.
