# Bước 0 — khung TikTok YouTube Studio

Phạm vi: Python 3.12, cửa sổ PySide6 trống, hợp đồng đồng bộ có type hint,
lỗi tiếng Việt, hủy tác vụ, đường dẫn an toàn và fake trong bộ nhớ. Không có
dịch vụ mạng, OAuth, SQLite hay tải/upload thật. Không commit/push.

1. Kiểm tra Git và README; giữ nguyên nội dung đầu, chỉ nối giới thiệu.
2. Tạo cây thư mục/gói, cấu hình cache nội bộ và môi trường Python 3.12.
3. Viết test hợp đồng, đường dẫn, hủy và fake trước; chạy để xác nhận thiếu triển khai.
4. Viết contracts/errors/core/fakes tối thiểu và main.py; ghim đủ 8 dependency.
5. Ghi quy tắc sở hữu trong AGENTS.md, hai file hướng dẫn trỏ về AGENTS.md.
6. Cài dependency, chạy toàn bộ pytest và kiểm tra cửa sổ bằng Qt offscreen.
7. Kiểm tra diff/status, báo danh sách file và kết quả; dừng ở Bước 0.

Quy ước: tiến độ là float [0, 1], callback đồng bộ trên luồng gọi;
CancelToken dùng threading.Event. Các dịch vụ chạy trên worker do UI quản lý.
HistoryRepository nhận bản ghi Mapping, trả dict; khóa job là int.
Phân biệt gốc ghi dữ liệu (cạnh exe khi frozen) và gốc tài nguyên (_MEIPASS).
Chặn mọi reparse point Windows, symlink và đường dẫn nằm ngoài gốc.
Không có yêu cầu bắt buộc ghi file ngoài dự án.
