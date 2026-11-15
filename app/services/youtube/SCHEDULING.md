# Đối chiếu lịch công khai — 2026-11-14

Nguồn chính thức đã đọc trước khi triển khai:

- [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert):
  cho phép ghi `status.publishAt`, `status.privacyStatus` khi `part` gồm `status`;
  kết quả thành công là tài nguyên video, chưa chứng minh video đã công khai.
- [status.publishAt](https://developers.google.com/youtube/v3/docs/videos#status.publishAt):
  chỉ đặt được cho video private chưa từng được công khai; thời gian dùng ISO 8601.
  Thời gian trong quá khứ có thể làm video công khai ngay. Khi dùng videos.update,
  phải gửi cả privacyStatus=private dù video đang private.

Ứng dụng chỉ hẹn giờ qua upload mới, luôn gửi private và UTC RFC 3339 hậu tố Z.
Giới hạn tối thiểu 10 phút và tối đa 365 ngày là chính sách của ứng dụng, không
phải giới hạn được hai tài liệu trên công bố. Kiểm tra lại trước lúc bắt đầu upload.
Resumable retry dùng lại phiên/video đã nhận, không gọi update để đổi lịch ngầm.

DB giữ SCHEDULED và uploaded_at=NULL sau upload. sync_scheduled chỉ chuyển
UPLOADED khi videos.list trả đúng video, đúng channelId và privacyStatus=public,
không có dấu hiệu xử lý thất bại. uploaded_at là lúc API xác nhận công khai.
Chỉ quá giờ hẹn chưa đủ để kết luận thành công: giữ SCHEDULED, lưu
schedule_needs_review=true cùng error_message tiếng Việt; không tạo enum mới.

UI hiện tại chưa đọc UploadResult.status; lượt này không sửa UI/workers. Bên UI
cần dùng status=SCHEDULED và cờ cần kiểm tra khi tích hợp màn hình hẹn giờ v2,
không dùng thông báo “đã công khai” chung cho mọi kết quả upload.
