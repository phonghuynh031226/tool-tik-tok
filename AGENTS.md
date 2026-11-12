# Quy tắc làm việc — TikTok YouTube Studio

## Phạm vi bắt buộc

- Thư mục làm việc duy nhất: `D:\DU AN CA NHAN\tool-tik-tok`.
- Không tạo/sửa/xóa file ngoài thư mục này; không tạo worktree bên ngoài.
- `.venv`, công cụ tải về, cache, temp, bytecode và dữ liệu test phải ở trong dự án.
  Dot-source `scripts/project-env.ps1` trước khi cài, chạy hoặc test.
- Nếu thao tác bắt buộc ghi ngoài dự án, báo chủ dự án trước khi thực hiện.
- Không commit, không push; cấm `git reset --hard` và `git clean`.
- Không ghi đè README hiện có; phần giới thiệu chỉ được nối cuối.

## Sở hữu thư mục

| AI | Phạm vi sở hữu |
| --- | --- |
| Codex | `app/contracts.py`, `app/errors.py`, `app/core/`, `app/services/tiktok/`, `app/services/youtube/`, `app/db/`, `app/security/`, `tests/core/`, `tests/services/`, cấu hình build và `build/` |
| Antigravity | `app/ui/`, `app/workers/`, `app/services/gemini/`, `assets/`, `tests/ui/` |

Khung Bước 0 được tạo theo yêu cầu chủ dự án. Từ các bước sau, không sửa vùng
của AI khác khi chưa phối hợp rõ ràng. `main.py`, `app/services/fakes.py` và cấu hình
chung cần phối hợp trước khi sửa đồng thời.

## Hợp đồng đóng băng

- `app/contracts.py` đóng băng sau Bước 0. Không tự đổi trường, chữ ký, kiểu hay ngữ nghĩa.
- Muốn đổi phải ghi đề xuất trong `docs/CONTRACT_CHANGES.md` để chủ dự án duyệt trước.
- Dùng cùng hợp đồng giữa backend và UI; không tạo bản sao hợp đồng ở thư mục khác.
- Quy ước callback: float từ 0.0 đến 1.0, chạy đồng bộ trên luồng gọi.
  UI tự chuyển công việc chậm sang worker và chuyển callback thành Qt signal.

## Bảo mật và hành vi

- Cấm hardcode API key, OAuth client secret, access/refresh token hoặc thông tin đăng nhập.
- Không log dữ liệu nhạy cảm, URL chứa credential, payload OAuth hoặc nội dung secret store.
- Secret thật phải đi qua SecretStore; không lưu key/token vào settings hoặc lịch sử SQLite.
- Không tự đăng: người dùng phải xem/sửa nội dung, xác nhận quyền sử dụng và xác nhận upload.
  `rights_confirmed` không thay thế nút xác nhận upload trong UI.
- Mặc định privacy là private. Không tích hợp dịch vụ thật trong Bước 0.
- Fake chỉ cho dev/test, không dùng để chứng minh tích hợp thật hoạt động.
- Không báo “hoàn thành” khi chưa chạy kiểm thử thật; báo đúng lệnh, kết quả và test bỏ qua.
- Không commit/push, không mở rộng công việc sau Bước 0 khi chưa được yêu cầu.
