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


## Đề xuất — Prompt tự động hóa, CHỜ CHỦ DỰ ÁN DUYỆT

Yêu cầu: nhiều mẫu prompt có tên, chọn mẫu rồi dán link để tải -> tạo nội dung ->
upload riêng tư và hẹn công khai theo các khung giờ liên tiếp; qua 23:00 chuyển
sang 00:00 ngày tiếp theo. Cho phép mẫu đặt rõ made_for_kids=False.

Thay đổi ngữ nghĩa cần duyệt:
- Trước: mọi video phải được người dùng xem/sửa, xác nhận quyền và xác nhận upload
  riêng trong UI; UploadRequest.rights_confirmed không thay thế xác nhận upload.
- Đề xuất sau: giữ nguyên chế độ thủ công. Chế độ tự động có thao tác bật quyền
  tự upload rõ ràng cho một phiên chạy, ràng buộc mẫu và kênh đích, có xác nhận
  quyền sử dụng. Trong phiên đó, cho phép upload nội dung AI tạo ra mà không
  bắt xem/duyệt từng video. Prompt đơn thuần không tự cấp quyền upload.
- Chữ ký/kiểu hiện tại: UploadRequest, YouTubeService.upload và cơ chế
  confirm_upload hiện có chưa sửa. Không tái sử dụng rights_confirmed làm quyền
  tự đăng. Chi tiết hợp đồng biểu diễn chính sách/ủy quyền riêng phải được duyệt
  trước khi thêm vào contracts.py; chưa có triển khai hay thay đổi hợp đồng.

Thiết kế đề nghị: AI chỉ phân tích prompt thành cấu hình có thể xem/sửa (mẫu,
kênh, ngày/giờ bắt đầu, khoảng cách, múi giờ, đối tượng, hướng dẫn nội dung).
Bộ lập lịch xác định thời gian bằng mã và lưu SQLite; không để AI tự suy đoán giờ
mỗi lần. Mặc định múi giờ Asia/Ho_Chi_Minh, cần chọn ngày bắt đầu; giờ đã qua
không được chuyển thành đăng ngay. Lưu mẫu và tiến độ qua lần mở app; xử lý lỗi,
trùng link, retry và trạng thái upload chưa rõ để tránh đăng lặp. Có tạm dừng/dừng.
Nội dung không dành trẻ em là lựa chọn được người dùng xác nhận, không phải AI
phân loại độ tuổi hay xác nhận bản quyền.

Phạm vi UI/backend/test: trang Tự động hóa quản lý mẫu, hàng đợi/link và lịch dự
kiến; backend tái dùng TikTok/Gemini/YouTube thật, lưu bền vững chính sách/tác vụ;
test phân tích prompt, đổi ngày/múi giờ, giờ quá hạn, khởi động lại, lỗi/retry,
chặn upload ngoài phiên đã cho phép, fake-mode và mock end-to-end. Chưa gọi dịch
vụ thật, chưa upload. Quyết định: CHỜ DUYỆT, chưa sửa AGENTS.md/contracts.py.

### Quyết định chủ dự án — chế độ Hoạt động đã duyệt
Chủ dự án xác nhận “đúng” cho trang danh sách prompt, một prompt Hoạt động,
và dán link ở Tổng quan tự tải/tạo/đăng không duyệt từng video. Bật Hoạt động là
ủy quyền riêng cho phiên chạy trên kênh đã chọn; vẫn phải xác nhận quyền sử dụng
khi bật. Quy trình thủ công giữ nguyên. Triển khai tái dùng các hợp đồng hiện có,
không thêm/sửa app/contracts.py. Quyền thực thi không lấy từ nội dung prompt và
không tự bật lại sau khởi động; lịch/mẫu được lưu bền vững.

## 2026-11-17: explicit enable click replaces repeated activation dialog
User explicitly requested removing the recurring activation/checkbox dialog.
Accepted UI behavior: pressing Bật hoạt động authorizes that prompt on the
currently selected connected channel for this session. No implicit channel
fallback to another account, no startup execution, no execution until a fresh
user paste, and existing backend upload validation remains. Controller's
explicit authorization arguments remain; no contracts.py edits or API changes.
This user-requested interaction supersedes the earlier repeated-dialog design.

## 2026-11-17: per-prompt target channel preference
User requested a fixed channel selector or Automatic using YouTube Channels'
marked default. Added nullable target_channel_id only in AutomationStore's own
SQLite prompt table, with legacy rows migrated to Automatic. No contracts.py
field/signature/semantics edits. Target resolved on explicit enable and remains
fixed until deactivation; no fallback from disconnected explicit targets.
