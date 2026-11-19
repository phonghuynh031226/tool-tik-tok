# Tự động hóa theo prompt

1. Mở trang Tự động hóa → Thêm prompt. Nhập tên và lệnh, ví dụ:
   “Khi tôi dán link TikTok, tự tải, tạo tiêu đề/mô tả bằng tiếng Việt, đăng
   công khai YouTube, không dành cho trẻ em.”
2. Bấm Phân tích prompt, kiểm tra chính sách AI đã hiểu rồi Lưu prompt.
3. Chọn kênh YouTube trong ứng dụng rồi bấm Bật hoạt động. Nút này cho phép
   tự chạy/đăng theo prompt trong phiên, không mở hộp xác nhận lặp lại. Chỉ một
   mẫu hoạt động cùng lúc; không có kênh hợp lệ thì app báo cần chọn kênh.
4. Qua Tổng quan, dán link bằng Ctrl+V hoặc nút Dán. Không cần bấm các bước
   tải/tạo/đăng. Chờ hoàn tất rồi dán video tiếp. Kết quả lưu trong lịch sử.
5. Bấm Tắt để quay về thủ công. Đóng app hết quyền chạy; mở lại cần bật lại.

Có thể thêm nhiều mẫu và xóa mẫu không dùng. Lịch lặp lưu bền vững qua lần mở
app; mẫu hẹn giờ dùng UTC+7, chọn khung tương lai, qua 23:00 sang ngày tiếp.
Đặt chỗ tối thiểu 15 phút trước thời điểm nhận link, kiểm tra còn >=10 phút trước
upload; nếu xử lý quá lâu thì dừng, không đổi thành đăng ngay. Không tự phát
lại tác vụ khi app mở lại, lỗi, trùng link/video hoặc kết quả upload chưa rõ.
Tắt trong khi upload có thể không thu hồi được video đã được YouTube nhận;
kiểm tra lịch sử/kênh khi trạng thái yêu cầu kiểm tra. Mẫu không có quyền
thực thi mã, đọc file, chọn kênh ngoài phiên hay tự xác nhận bản quyền.

Gemini cần key trong SecretStore. Fake-mode chỉ dùng chính sách demo và mô
phỏng; không phân tích AI thật hoặc gọi YouTube upload. Chế độ thủ công giữ
bước duyệt upload cũ. contracts.py không đổi.

Bằng chứng kiểm thử xem docs/superpowers/plans/2026-11-16-prompt-automation.md.
Chưa có upload thật để kiểm chứng tích hợp. Hai lần phân tích Gemini thật đã
được cho phép riêng và đều thất bại; lần thứ hai trả HTTP 400. Chưa xác nhận
parser hoạt động với key/model hiện tại; nguyên nhân từ chối cụ thể chưa rõ.

Thử lại sau lỗi: dán lại link sau khi bật lại prompt. Lỗi/hủy trước bước upload
cho phép chạy lại và giữ bản ghi lần thử trước. Video đã hoàn tất hoặc đang xử lý
vẫn bị chặn. Nếu lần trước bị ngắt và chưa rõ kết quả, app yêu cầu kiểm tra kênh,
lịch sử rồi xác nhận “Chưa đăng, thử lại”. Không tự phát lại khi mở app.

Lịch mỗi giờ chọn khung trống gần nhất còn đủ thời gian xử lý, dựa vào giờ
UTC+7 hiện tại và các tác vụ đã thực sự giữ lịch. Ví dụ18:04 →19:00; link kế
→20:00. Lần lỗi/hủy trước upload không làm mất một giờ. Qua23:00 tiếp tục
00:00,01:00 ngày sau. Khung đã upload hoặc chưa rõ kết quả vẫn được giữ.

Kênh đăng theo prompt: chọn trong hộp Thêm prompt hoặc ngay trên thẻ prompt.
“Tự động” dùng kênh đánh dấu Mặc định tại mục Kênh YouTube, không dùng lựa chọn
tạm của Tổng quan. Kênh cố định được lưu riêng; mất kết nối sẽ báo lỗi, không
chuyển kênh khác. Kênh được chốt lúc bật; muốn đổi hãy tắt prompt trước.
Prompt cũ tự dùng chế độ Tự động. Không có kênh mặc định thì cần chọn/đặt mặc định.

Mô hình mặc định: trong Cài đặt chọn model rồi bấm Đặt làm mặc định. App lưu
riêng lựa chọn này; model thử tạm hoặc fallback không ghi đè mặc định. Khi mở
app, các ô chọn ưu tiên mặc định nếu model còn khả dụng. Yêu cầu có model riêng
vẫn được ưu tiên cho lần chạy đó.
Files API: bật để gửi MP4 lên Gemini phân tích video; tắt chủ yếu dùng metadata.
Prompt tùy chỉnh là mẫu viết nội dung, không phải quy trình tự động tải/đăng.
Để trống dùng mẫu có sẵn; {title}/{description} chèn nội dung gốc.
