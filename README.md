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


## Cài đặt và đóng gói Windows

Phần này bổ sung hướng dẫn triển khai. Các mô tả Bước 0 phía trên được giữ nguyên
để ghi lại trạng thái ban đầu. Backend TikTok/YouTube, SQLite và security đã có
triển khai; `main.py` hiện vẫn mở cửa sổ trống, chưa nối thành giao diện đầy đủ.
Không coi EXE này là sản phẩm hoàn chỉnh có thể thao tác toàn bộ luồng qua UI.

### Yêu cầu hệ thống và cài đặt

- Windows 10/11 64-bit, Python 3.12 64-bit để phát triển/build; máy chạy bản EXE
  không cần cài Python. Chừa vài GB cho `.venv`, Qt, build và video.
- Cần Internet cho TikTok, Gemini và Google OAuth/YouTube; cần trình duyệt hệ thống
  và Windows Credential Manager. Không lưu key/token vào file thường.
- Chọn thư mục người dùng có quyền ghi, tránh Program Files. Đường dẫn có dấu cách
  được hỗ trợ. Không cần sửa mã theo một ổ đĩa hay thư mục cố định.

Mở PowerShell trong thư mục dự án (dùng đường dẫn thực tế của bạn):

```powershell
. .\scripts\project-env.ps1
$env:TMPDIR = $env:TEMP
$env:PIP_CONFIG_FILE = 'NUL'
# Chỉ tạo môi trường khi chưa có .venv; python phải là bản 3.12:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated --cache-dir "$env:PIP_CACHE_DIR" install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
```

`requirements.txt` dành cho runtime; `requirements-dev.txt` bổ sung pytest,
pytest-qt và PyInstaller. TEMP/TMP/TMPDIR, pip cache, bytecode và cache PyInstaller
phải ở trong dự án khi cài/test/build.

### FFmpeg và Qt Multimedia

Tải bộ FFmpeg dành cho Windows từ nguồn tin cậy theo liên kết tại
[FFmpeg Downloads](https://ffmpeg.org/download.html). Đặt `ffmpeg.exe` và
`ffprobe.exe` vào `bin/`. Nên dùng bản static hoặc phân phối đủ các DLL đi kèm.
Backend không tự cài công cụ và không tìm công cụ tùy ý qua PATH.

Build sẽ copy đúng hai file EXE này vào `dist/TikTokYouTubeStudio/bin/` nếu có;
thiếu file sẽ có cảnh báo. Qt Multimedia và plugin/DLL Qt được đưa vào cấu hình
PyInstaller riêng; thư viện codec nội bộ của Qt không thay thế ffprobe cho backend.
Kiểm tra giấy phép FFmpeg/codec/Qt trước khi phân phối.

### Gemini API key

Tạo key trong [Google AI Studio](https://aistudio.google.com/apikey), chọn project
và kiểm tra billing/quota theo nhu cầu. Nhập qua chức năng cấu hình của UI khi
được tích hợp; key phải đi qua SecretStore/Windows Credential Manager. Không đặt
key vào mã nguồn, settings.json, SQLite, log, requirements hoặc gói EXE.

### Google OAuth Desktop và kênh YouTube

1. Tạo project trong [Google Cloud Console](https://console.cloud.google.com/),
   bật **YouTube Data API v3**.
2. Cấu hình OAuth consent screen/Google Auth Platform: tên ứng dụng, email hỗ trợ,
   audience và các scope `youtube.upload`, `youtube.readonly`.
3. Tạo OAuth Client ID loại **Desktop app**, tải client JSON về vị trí riêng.
   Người dùng chọn file này khi kết nối; ứng dụng chỉ đọc và lưu nội dung trong
   SecretStore, không copy file vào repo/dist.
4. Đăng nhập trong trình duyệt hệ thống. OAuth dùng PKCE và loopback
   `127.0.0.1` cổng ngẫu nhiên; đừng chặn callback này bằng firewall.
5. Xem tên/mã kênh trả về và xác nhận đúng kênh trước khi upload. Phải chọn rõ
   `made_for_kids`, kiểm tra quyền sử dụng, xem/sửa nội dung và xác nhận upload.
   Mặc định privacy là `private`; không có tự động đăng sau khi kết nối.

`youtube.upload` phục vụ upload đã được xác nhận; `youtube.readonly` phục vụ đọc
kênh đích và trạng thái xử lý. Với consent screen **External / Testing**, thêm tài
khoản vào **Test users**. Refresh token cho các scope YouTube ở chế độ này thường
hết hạn sau khoảng **7 ngày**, nên có thể phải disconnect rồi kết nối/consent lại.
Xem [vòng đời refresh token](https://developers.google.com/identity/protocols/oauth2#expiration).
OAuth verification và YouTube API compliance audit là các quy trình khác nhau.

### Quota và giới hạn Private

Hạn mức thường được nhắc tới là **10.000 đơn vị/ngày**. Nhiều hướng dẫn cũ dùng
mốc **~1.600 đơn vị/upload** (khoảng 6 upload nếu chỉ tiêu quota cho upload).
**Không coi mốc 1.600 là chi phí hiện hành đã được xác minh**: lần bổ sung này
không truy cập được tài liệu trực tuyến để đối chiếu. Kiểm tra
[chi phí quota](https://developers.google.com/youtube/v3/determine_quota_cost),
[videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
và quota thực tế trong Cloud Console trước khi ước lượng số video/ngày.
Các yêu cầu đọc kênh/trạng thái và yêu cầu lỗi cũng có thể tiêu quota.

Video upload từ một số project API chưa qua audit có thể bị Google giới hạn ở
**Private**, dù ứng dụng yêu cầu public/unlisted. Việc chuyển consent screen sang
Production không tự gỡ giới hạn này; tham khảo điều kiện audit tại videos.insert.
Không thử vượt quota, giới hạn tài khoản hoặc chính sách của YouTube.

### Build EXE onedir, không console

Cài `requirements-dev.txt`, đóng bản EXE đang chạy, rồi chạy `build.bat` bằng đường
 dẫn đầy đủ hoặc mở trực tiếp. Batch tự lấy thư mục chứa chính nó bằng `%~dp0`,
chuyển đến đó và dùng `.venv`, nên không phụ thuộc thư mục làm việc hiện tại.

Cấu hình `TikTokYouTubeStudio.spec` dùng `EXE(console=False, exclude_binaries=True)`
và `COLLECT`: đây là chế độ **--onedir / --windowed**. Khi build từ spec, không
truyền thêm hai cờ CLI này vì chúng đã được mã hóa trong spec.

Kết quả dự kiến: `dist/TikTokYouTubeStudio/TikTokYouTubeStudio.exe`.
Phân phối **toàn bộ thư mục TikTokYouTubeStudio**, gồm `_internal` và `bin` nếu có;
không chỉ copy riêng file EXE. Có thể đặt cả thư mục ở một vị trí có quyền ghi khác
và chạy từ working directory bất kỳ. Backend lấy thư mục dữ liệu cạnh EXE;
resource Qt/assets lấy từ bundle `_MEIPASS`. Không tạo dữ liệu dưới `_internal`.

Build không thu gom config/data/downloads/logs của dự án, client_secret, credentials,
token, DB hay video đã tải. Không chép những dữ liệu này vào dist bằng tay.
Chưa có chữ ký số; Windows SmartScreen có thể yêu cầu người dùng kiểm tra nguồn.

### Lỗi thường gặp và kiểm thử

- `PyInstaller is missing`: cài requirements-dev.txt bằng đúng Python trong .venv.
- Thiếu Qt/platform/multimedia plugin: giữ nguyên `_internal`, dùng môi trường sạch
  chỉ có PySide6; kiểm tra log build. Không trộn PyQt5/PyQt6 vào bundle.
- Thiếu ffprobe/ffmpeg: đặt đúng hai EXE vào bin rồi build lại; nếu dùng bản shared,
  bảo đảm DLL của bộ công cụ cũng có mặt ở máy chạy.
- `invalid_grant` hoặc `AuthExpired`: kiểm tra thời gian hệ thống, Test users,
  hạn 7 ngày của Testing; disconnect rồi consent lại với đúng Desktop client.
- `quotaExceeded`: dừng retry; kiểm tra quota Console và chờ hạn mức được cấp lại.
- Upload bị Private: kiểm tra trạng thái audit/project, không chỉ privacy trong UI.
- TikTok private/region/age/DRM: backend sẽ từ chối; không cố vượt giới hạn truy cập.
- Symlink/junction hoặc thư mục chỉ đọc: chọn thư mục thật, có quyền ghi. Backend
  vẫn chặn đường dẫn thoát gốc; cờ xác nhận đường dẫn ngoài chưa cấp quyền tự ghi.
- Build chưa nối UI: cửa sổ trống là trạng thái main.py hiện tại, không phải bằng
  chứng dịch vụ mạng đã chạy thành công.

```powershell
. .\scripts\project-env.ps1
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -ra
```

Test dùng mock, không upload thật. Nếu môi trường chặn tạo symlink/junction,
phải báo rõ test bỏ qua/chưa chạy; không coi đó là đã kiểm chứng đủ.

### Bản quyền và điều khoản

Chỉ tải và đăng lại nội dung bạn sở hữu hoặc đã được cấp phép phù hợp. Việc một
video công khai hoặc có thể tải được không đồng nghĩa có quyền đăng lại; nhạc,
hình ảnh và người xuất hiện có thể có quyền riêng. Tuân thủ điều khoản TikTok,
YouTube và quy định áp dụng. Ứng dụng không xóa watermark, vượt DRM hay khẳng định
“không watermark” dựa vào tên format. Người dùng chịu trách nhiệm xác nhận quyền
sử dụng và kênh đích trước mỗi lần upload.
