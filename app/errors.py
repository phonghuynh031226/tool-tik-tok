"""Application errors with safe Vietnamese UI messages; never log raw details."""


class AppError(Exception):
    user_message = 'Đã xảy ra lỗi. Vui lòng thử lại.'
    retryable = False


class InvalidUrl(AppError):
    user_message = 'Liên kết không hợp lệ. Vui lòng kiểm tra lại.'


class DisallowedHost(AppError):
    user_message = 'Tên miền này không được phép sử dụng.'


class DownloadFailed(AppError):
    user_message = 'Không tải được video. Vui lòng thử lại.'
    retryable = True


class Cancelled(AppError):
    user_message = 'Tác vụ đã được hủy.'


class QuotaExceeded(AppError):
    user_message = 'Đã hết hạn mức dịch vụ. Vui lòng thử lại sau khi hạn mức được cấp lại.'


class AuthExpired(AppError):
    user_message = 'Phiên đăng nhập đã hết hạn. Vui lòng kết nối lại tài khoản.'


class NetworkError(AppError):
    user_message = 'Không thể kết nối mạng. Vui lòng kiểm tra kết nối và thử lại.'
    retryable = True


class ContentInvalid(AppError):
    user_message = 'Nội dung chưa hợp lệ hoặc chưa được xác nhận. Vui lòng kiểm tra lại.'
