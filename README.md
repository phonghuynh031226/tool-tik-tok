# tool-tik-tok

## TikTok YouTube Studio

Ứng dụng Windows Desktop dùng Python 3.12 và PySide6. Luồng dự kiến:
nhập link TikTok → tải MP4 bằng yt-dlp → Gemini gợi ý tiêu đề/mô tả → người dùng
xem và sửa → xác nhận upload YouTube qua Data API v3 và OAuth Desktop → lưu lịch sử SQLite.
Không tự đăng video khi người dùng chưa xác nhận.

### Trạng thái Bước 0

Chỉ có khung cửa sổ, hợp đồng dịch vụ, lỗi tiếng Việt, hủy tác vụ, kiểm soát đường dẫn
và fake cho dev/test. Chưa có tải video, Gemini, OAuth, SQLite hoặc upload thật.
Fake download trả đường dẫn mẫu **không tạo MP4**; fake upload không gửi dữ liệu đi đâu.
Fake secret/settings/history chỉ ở trong bộ nhớ và mất khi thoát.

### Môi trường và chạy thử (PowerShell, tại thư mục dự án)

```powershell
. .\scripts\project-env.ps1
# Khi đã có Python 3.12, tạo môi trường nếu chưa tồn tại:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest
```

Chỉ chạy lệnh tạo `.venv` với interpreter Python 3.12. Môi trường được chuẩn bị ở
Bước 0 dùng runtime 3.12 trong `.cache/python` khi máy chưa có bản phù hợp.
`scripts/project-env.ps1` đặt TEMP/TMP/PIP_CACHE_DIR/PYTHONPYCACHEPREFIX và cache uv
vào dự án. Pytest dùng `.tmp/pytest` và `.cache/pytest`. Không cần ghi ngoài dự án.

`app/core/paths.py` tách gốc ghi dữ liệu cạnh exe và gốc tài nguyên `_MEIPASS` của
PyInstaller; các API đường dẫn từ chối symlink, junction/reparse point và đường dẫn
thoát gốc. Kiểm tra đường dẫn không thay thế quyền filesystem: bên ghi file phải
tránh việc bên khác thay đổi liên kết giữa lúc kiểm tra và lúc mở file.

Quy tắc phối hợp: [AGENTS.md](AGENTS.md). Hợp đồng đóng băng:
`app/contracts.py`; đề xuất thay đổi ghi tại [docs/CONTRACT_CHANGES.md](docs/CONTRACT_CHANGES.md).
