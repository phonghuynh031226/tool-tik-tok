# Chẩn đoán và giới hạn kiểm chứng — 2026-11-17

Đo bằng mock trước sửa:

- Hai caller threads vào get_channel: cùng 1 HTTP, peak request đang chạy = 1.
  RLock của facade đã tuần tự hóa API; chưa chứng minh có hai request thực chạy
  đồng thời trên cùng HTTP trong backend hiện tại.
- FetchAccountsWorker và YouTubeRestoreWorker có thể cùng gọi list_accounts:
  2 lượt nạp, peak=2 trên probe không có facade lock.
- Hai bản credentials hết hạn của cùng grant cùng refresh: 2 lần gọi refresh.

Sau sửa, regression kiểm tra HTTP riêng cho mỗi request, đóng cả khi lỗi; hai
worker khởi động dùng single-flight snapshot do một worker nạp tuần tự. Refresh
có khóa theo grant và waiter nạp token mới từ đúng SecretStore namespace.
Sau mutation, snapshot bị vô hiệu; làm mới chủ động vẫn đọc lại backend.

Nguồn chính thức về HTTP riêng từng luồng:
https://googleapis.github.io/google-api-python-client/docs/thread_safety.html
Timeout httplib2 là timeout cấp socket cho connect/read (30 giây); OAuth/refresh
dùng requests với connect=10/read=30 giây. Retry mạng/5xx giữ tối đa 5 lần chờ.
Không tắt xác minh chứng chỉ TLS. Mã Python không thể bắt và phục hồi một native
access violation; không coi except Exception là biện pháp chặn lỗi native.

Probe TLS cục bộ, không gọi mạng: Python 3.12.16/OpenSSL 3.5.9; Qt 6.12.0 build
OpenSSL 3.5.4, runtime 3.6.5, supportsSsl=True. Các số khác nhau chưa chứng minh
không tương thích. Trong baseline pytest từng có thông báo first-chance Windows
0xc0000139 tại Qt tải avatar nhưng pytest vẫn exit 0; khác lỗi AV 0xc0000005 được
báo trong sự cố. Service tests nay mock cả Qt avatar để bảo đảm offline.

Chưa tái hiện native AV gốc, chưa dùng OAuth/API/keyring thật hoặc mô phỏng mạng
Windows thực. Cần dùng logs/crash.log và phiên bản ở studio.log nếu tái diễn.
