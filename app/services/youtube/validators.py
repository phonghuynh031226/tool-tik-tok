"""Shared pure validators. No OAuth, filesystem or network side effects."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import re

from app.contracts import UploadRequest
from app.errors import ContentInvalid, ScheduleInPast


def invalid(message: str) -> ContentInvalid:
    error = ContentInvalid()
    error.user_message = message
    return error


def _text(value, *, multiline=False):
    if not isinstance(value, str) or '<' in value or '>' in value:
        raise invalid('Nội dung phải là chuỗi và không được chứa ký tự < hoặc >.')
    if any(ord(char) < 32 and not (multiline and char in '\n\r\t') for char in value):
        raise invalid('Nội dung chứa ký tự điều khiển không hợp lệ.')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise invalid('Nội dung không phải UTF-8 hợp lệ.') from None


def validate_title(title: str) -> None:
    _text(title)
    if not title.strip() or len(title) > 100:
        raise invalid('Tiêu đề phải có nội dung và không vượt quá 100 ký tự.')


def validate_description(description: str) -> None:
    _text(description, multiline=True)
    if len(description.encode('utf-8')) > 5000:
        raise invalid('Mô tả không được vượt quá 5000 byte UTF-8.')


def validate_tags(tags: list[str]) -> None:
    if not isinstance(tags, list):
        raise invalid('Tags phải là danh sách chuỗi.')
    for tag in tags:
        _text(tag)
        if not tag.strip():
            raise invalid('Tag không được để trống.')
    # YouTube counts commas and quotes required for tags containing spaces.
    length = sum(len(tag) + (2 if ' ' in tag else 0) for tag in tags) + max(len(tags) - 1, 0)
    if length > 500:
        raise invalid('Tổng tags, dấu phẩy và dấu ngoặc kép cho tag có khoảng trắng không được vượt quá 500 ký tự.')


def validate_publish_at(publish_at: datetime | None, *, now: datetime | None = None) -> datetime | None:
    """Application policy: aware UTC instant, at least 10 minutes, at most 365 days.

    These bounds are ours; YouTube's publishAt requires a private, never-public
    video. A past publishAt may publish immediately (see SCHEDULING.md).
    """
    if publish_at is None:
        return None
    if not isinstance(publish_at, datetime) or publish_at.tzinfo is None or publish_at.utcoffset() is None:
        raise invalid('Thời điểm công khai phải là ngày giờ có múi giờ.')
    now = now if now is not None else datetime.now(timezone.utc)
    value = publish_at.astimezone(timezone.utc)
    if value - now < timedelta(minutes=10):
        error = ScheduleInPast()
        error.user_message = 'Thời điểm công khai phải cách hiện tại ít nhất 10 phút. Hãy chọn lại lịch hẹn.'
        raise error
    if value - now > timedelta(days=365):
        raise invalid('Chỉ được hẹn công khai trong vòng 365 ngày kể từ hiện tại.')
    return value


def validate_upload_request(req: UploadRequest) -> None:
    validate_title(req.title)
    validate_description(req.description)
    validate_tags(req.tags)
    validate_publish_at(req.publish_at)
    if req.rights_confirmed is not True:
        raise invalid('Bạn phải xác nhận quyền sử dụng video trước khi upload.')
    if not isinstance(req.made_for_kids, bool):
        raise invalid('Phải chọn rõ video có dành cho trẻ em hay không.')
    if req.privacy not in {'private', 'unlisted', 'public'}:
        raise invalid('Quyền riêng tư không hợp lệ.')
    if not isinstance(req.category_id, str) or not re.fullmatch(r'[0-9]{1,3}', req.category_id):
        raise invalid('Mã danh mục YouTube không hợp lệ.')
    if not isinstance(req.default_language, str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', req.default_language):
        raise invalid('Ngôn ngữ mặc định không hợp lệ.')


def create_upload_request(*, path: Path, title: str, description: str, tags: list[str],
                          made_for_kids: bool, privacy: str = 'private', rights_confirmed: bool = False,
                          category_id: str = '22', default_language: str = 'vi') -> UploadRequest:
    if not isinstance(made_for_kids, bool):
        raise invalid('Phải chọn rõ video có dành cho trẻ em hay không.')
    validate_title(title)
    validate_description(description)
    validate_tags(tags)
    return UploadRequest(path, title, description, list(tags), privacy, made_for_kids,
                         category_id, default_language, rights_confirmed)
