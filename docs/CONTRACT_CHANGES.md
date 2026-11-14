# Đề xuất thay đổi hợp đồng

`app/contracts.py` đóng băng sau Bước 0. Chưa có đề xuất thay đổi.

Mọi đề xuất phải ghi: lý do, chữ ký/kiểu trước và sau, bên bị ảnh hưởng,
kế hoạch cập nhật UI/backend/test và quyết định được chủ dự án chấp thuận.
Không sửa hợp đồng trước khi đề xuất được chấp thuận.

## V2 — đã được chủ dự án cho phép trong lượt chuẩn bị hợp đồng

Chỉ bổ sung, giữ nguyên các trường/chữ ký/giá trị mặc định cũ:

- `JobStatus.SCHEDULED`; `UploadRequest.publish_at: datetime | None = None`
  (phải có múi giờ), `channel_id: str | None = None` (tài khoản mặc định).
- `UploadResult.status: JobStatus = JobStatus.UPLOADED` để upload giả trả được
  `SCHEDULED`; constructor ba tham số cũ vẫn dùng được.
- Các dataclass `ChannelAccount`, `ChannelStats`, `VideoStats`: toàn bộ trường
  có mặc định; số liệu likes/comments không được cung cấp dùng `None`, không phải 0.
  Thời lượng tính bằng giây; datetime có múi giờ, `None` là chưa biết.
- `YouTubeService`: thêm list/add/remove/set-default account, thống kê kênh,
  danh sách video và `sync_scheduled() -> list[UploadResult]` (những video hẹn giờ
  đã chuyển sang xuất bản trong lần đồng bộ). API connect/disconnect/get_channel
  cũ tiếp tục thao tác tài khoản mặc định; upload chọn `req.channel_id`.
- `HistoryRepository.list_scheduled() -> list[HistoryRecord]` trả toàn bộ tác vụ
  SCHEDULED mới nhất trước. `StatsCache` lưu/nạp snapshot kênh và video; không có
  dữ liệu trả `None`/`[]`; save_videos thay toàn bộ danh sách của một kênh.

Bên ảnh hưởng: backend Codex và UI Antigravity. Fake cung cấp đầy đủ dữ liệu v2
cho UI qua `STUDIO_USE_FAKES=1`. Backend YouTube thật hiện giữ chức năng một tài
khoản; các tính năng v2 chưa triển khai báo lỗi rõ, đặc biệt từ chối hẹn giờ để
không vô tình đăng ngay. Không coi fake là bằng chứng tích hợp thật.
Schema SQLite v3 thêm scheduled_at/channel_id và bảng thống kê, giữ dữ liệu cũ.
Test field-layout cập nhật phần trường mới, giữ nguyên phần trường cũ và bổ sung
test constructor tương thích, migration và fake. Sau lượt này hợp đồng đóng băng lại.
