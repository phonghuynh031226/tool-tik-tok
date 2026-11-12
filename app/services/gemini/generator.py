"""Gemini AI Content Generator using official google-genai SDK."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from pydantic import BaseModel, Field

from app.contracts import ContentGenerator, GeneratedContent, SecretStore, SettingsStore, VideoMeta
from app.errors import AuthExpired, ContentInvalid, NetworkError, QuotaExceeded

logger = logging.getLogger(__name__)

# Default prompt template in Vietnamese
DEFAULT_PROMPT_TEMPLATE = (
    "Bạn là chuyên gia sáng tạo nội dung YouTube Shorts hàng đầu bằng tiếng Việt.\n"
    "Nhiệm vụ: Viết lại tiêu đề, mô tả, hashtags và thẻ tìm kiếm (tags) hấp dẫn chuẩn SEO "
    "cho YouTube Shorts dựa trên thông tin video TikTok sau:\n\n"
    "Tiêu đề gốc: {title}\n"
    "Mô tả gốc: {description}\n"
    "Tác giả: {author}\n"
    "Thời lượng: {duration} giây\n\n"
    "QUY TẮC BẮT BUỘC:\n"
    "- Tiêu đề: Tối đa 100 ký tự, cuốn hút, kích thích tò mò nhưng KHÔNG clickbait sai sự thật. "
    "Không chứa ký tự '<' hoặc '>'.\n"
    "- Mô tả: Chi tiết, chuẩn SEO, tối đa 5000 byte UTF-8. Không chứa ký tự '<' hoặc '>'.\n"
    "- Hashtags: Danh sách hashtag liên quan, KHÔNG chứa ký tự '#'.\n"
    "- Tags: Danh sách từ khóa tìm kiếm liên quan, tổng độ dài các tags không quá 500 ký tự. "
    "Không chứa ký tự '<' hoặc '>'.\n"
    "{video_context_instruction}"
)

NO_VIDEO_INSTRUCTION = (
    "- CHÚ Ý QUAN TRỌNG: Bạn chỉ được cung cấp tiêu đề và mô tả thô. "
    "TUYỆT ĐỐI KHÔNG ĐƯỢC tuyên bố đã xem video hay mô tả chi tiết cảnh quay, "
    "hình ảnh mà bạn không biết. Không bịa đặt chi tiết sai lệch."
)

VIDEO_ANALYZE_INSTRUCTION = (
    "- Video đã được cung cấp trực tiếp. Bạn được phép phân tích chi tiết hình ảnh, "
    "âm thanh và bối cảnh dựa trên nội dung video thực tế."
)


class ContentOutputSchema(BaseModel):
    """Structured output schema for Gemini content generation."""

    title: str = Field(description="Tiêu đề video YouTube Shorts tối đa 100 ký tự")
    description: str = Field(description="Mô tả chi tiết chuẩn SEO tối đa 5000 bytes")
    hashtags: list[str] = Field(description="Danh sách hashtags không bao gồm dấu #")
    tags: list[str] = Field(description="Danh sách từ khóa tìm kiếm tags không chứa < >")


def sanitize_text(text: str) -> str:
    """Remove prohibited < and > characters from text."""
    if not text:
        return ""
    return re.sub(r"[<>]", "", str(text)).strip()


def validate_and_sanitize_content(
    title: str,
    description: str,
    hashtags: list[str],
    tags: list[str],
) -> tuple[bool, str, GeneratedContent]:
    """Validate limits and sanitize content:

    - Title <= 100 chars, no < >
    - Description <= 5000 bytes UTF-8, no < >
    - Tags total <= 500 chars, no < >
    - Hashtags without #

    Returns (is_valid, error_reason, sanitized_content).
    """
    clean_title = sanitize_text(title)
    clean_desc = sanitize_text(description)
    clean_hashtags = [sanitize_text(h).lstrip("#") for h in hashtags if sanitize_text(h).lstrip("#")]
    clean_tags = [sanitize_text(t).lstrip("#") for t in tags if sanitize_text(t).lstrip("#")]

    # Check title
    if not clean_title:
        return False, "Tiêu đề không được để trống", GeneratedContent("", "", [], [])

    if len(clean_title) > 100:
        # Attempt clean truncation to 100 chars
        clean_title = clean_title[:100].rstrip()

    # Check description UTF-8 byte length
    desc_bytes = clean_desc.encode("utf-8")
    if len(desc_bytes) > 5000:
        # Attempt truncation at character boundary
        while len(clean_desc.encode("utf-8")) > 5000 and len(clean_desc) > 0:
            clean_desc = clean_desc[:-10]
        clean_desc = clean_desc.rstrip()

    # Check tags total length
    total_tags_len = sum(len(t) for t in clean_tags)
    if total_tags_len > 500:
        trimmed_tags: list[str] = []
        cur_len = 0
        for t in clean_tags:
            if cur_len + len(t) <= 500:
                trimmed_tags.append(t)
                cur_len += len(t)
            else:
                break
        clean_tags = trimmed_tags

    # Final verification after trimming
    if len(clean_title) > 100:
        return False, "Tiêu đề vượt quá 100 ký tự", GeneratedContent(clean_title, clean_desc, clean_hashtags, clean_tags)
    if len(clean_desc.encode("utf-8")) > 5000:
        return False, "Mô tả vượt quá 5000 bytes UTF-8", GeneratedContent(clean_title, clean_desc, clean_hashtags, clean_tags)
    if sum(len(t) for t in clean_tags) > 500:
        return False, "Tổng độ dài tags vượt quá 500 ký tự", GeneratedContent(clean_title, clean_desc, clean_hashtags, clean_tags)

    return True, "", GeneratedContent(
        title=clean_title,
        description=clean_desc,
        hashtags=clean_hashtags,
        tags=clean_tags,
    )


class GeminiContentGenerator(ContentGenerator):
    """Production ContentGenerator using google-genai SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_store: Optional[SecretStore] = None,
        settings_store: Optional[SettingsStore] = None,
        client_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._api_key = api_key
        self._secret_store = secret_store
        self._settings_store = settings_store
        self._client_factory = client_factory

    def _resolve_api_key(self) -> str:
        """Resolve API key safely without logging it."""
        if self._api_key:
            return self._api_key.strip()
        if self._secret_store:
            key = self._secret_store.get("gemini_api_key")
            if key and key.strip():
                return key.strip()
        env_key = os.environ.get("GEMINI_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()
        raise AuthExpired(
            "Chưa cấu hình khóa API Gemini. Vui lòng nhập API Key trong phần Cài đặt."
        )

    def _get_client(self) -> Any:
        api_key = self._resolve_api_key()
        if self._client_factory:
            return self._client_factory(api_key)
        from google import genai
        return genai.Client(api_key=api_key)

    def _handle_api_error(self, exc: Exception) -> None:
        """Map SDK errors to safe Vietnamese application exceptions."""
        err_str = str(exc)
        code = getattr(exc, "code", None)

        if code in (401, 403) or "API_KEY_INVALID" in err_str or "PERMISSION_DENIED" in err_str or "UNAUTHENTICATED" in err_str:
            raise AuthExpired(
                "Khóa API Gemini không hợp lệ hoặc đã hết hạn. Vui lòng kiểm tra lại trong Cài đặt."
            ) from exc

        if code == 429 or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.casefold():
            raise QuotaExceeded(
                "Đã hết hạn mức dịch vụ Gemini. Vui lòng thử lại sau khi hạn mức được cấp lại."
            ) from exc

        # Other network or temporary server errors
        raise NetworkError(
            "Không thể kết nối đến máy chủ Google Gemini. Vui lòng kiểm tra kết nối mạng và thử lại."
        ) from exc

    def list_models(self) -> list[str]:
        """List models supporting generateContent dynamically from API."""
        try:
            client = self._get_client()
            models_list = client.models.list()
            result: list[str] = []
            for m in models_list:
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions:
                    name = getattr(m, "name", "") or ""
                    clean_name = name.removeprefix("models/")
                    if clean_name:
                        result.append(clean_name)
            return result
        except AuthExpired:
            raise
        except Exception as exc:
            self._handle_api_error(exc)
            return []

    def test_connection(self) -> bool:
        """Test API connection and credentials without logging secrets."""
        try:
            client = self._get_client()
            # Request 1 model to verify credentials
            pager = client.models.list(config={"page_size": 1})
            for _ in pager:
                break
            return True
        except AuthExpired:
            raise
        except Exception as exc:
            self._handle_api_error(exc)
            return False

    def generate(self, meta: VideoMeta, settings: Mapping[str, Any]) -> GeneratedContent:
        """Generate optimized YouTube Shorts metadata with validation and retry."""
        client = self._get_client()

        # Resolve model name
        model_name = settings.get("model") or "gemini-2.0-flash"

        # Check Files API option
        analyze_video = bool(settings.get("analyze_video_file", False))
        if self._settings_store and "analyze_video_file" not in settings:
            analyze_video = bool(self._settings_store.get("analyze_video_file", False))

        video_path = settings.get("video_path")
        uploaded_file = None

        if analyze_video and video_path and Path(video_path).exists():
            instruction_text = VIDEO_ANALYZE_INSTRUCTION
            try:
                uploaded_file = client.files.upload(file=str(video_path))
            except Exception as e:
                logger.warning("Files API upload failed, falling back to metadata: %s", str(e))
                instruction_text = NO_VIDEO_INSTRUCTION
        else:
            instruction_text = NO_VIDEO_INSTRUCTION

        # Build prompt
        prompt_template = settings.get("prompt_template")
        if not prompt_template and self._settings_store:
            prompt_template = self._settings_store.get("gemini_prompt_template")
        if not prompt_template:
            prompt_template = DEFAULT_PROMPT_TEMPLATE

        prompt = prompt_template.format(
            title=meta.title or "Không có tiêu đề",
            description=meta.description or "Không có mô tả",
            author=meta.author or "Không rõ",
            duration=meta.duration or 0.0,
            video_context_instruction=instruction_text,
        )

        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ContentOutputSchema,
            temperature=0.7,
        )

        contents: list[Any] = [prompt]
        if uploaded_file is not None:
            contents.append(uploaded_file)

        # Retry logic: up to 2 re-generations if content is invalid or temporary failure
        max_attempts = 3
        last_error: Optional[Exception] = None

        try:
            for attempt in range(max_attempts):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    raw_text = getattr(response, "text", "") or ""
                    try:
                        data = json.loads(raw_text)
                    except Exception as json_err:
                        if attempt < max_attempts - 1:
                            time.sleep(0.5 * (2**attempt))
                            continue
                        raise ContentInvalid("Dữ liệu JSON sinh từ AI không hợp lệ.") from json_err

                    # Validate and sanitize limits
                    is_valid, reason, sanitized = validate_and_sanitize_content(
                        title=data.get("title", ""),
                        description=data.get("description", ""),
                        hashtags=data.get("hashtags", []),
                        tags=data.get("tags", []),
                    )

                    if is_valid:
                        return sanitized

                    # If not valid after auto-trim, retry with clarification in prompt
                    if attempt < max_attempts - 1:
                        contents = [
                            f"{prompt}\nLƯU Ý LỖI LẦN TRƯỚC: {reason}. Bắt buộc tiêu đề ≤100 ký tự, mô tả ≤5000 bytes, không dùng ký tự < >."
                        ]
                        if uploaded_file is not None:
                            contents.append(uploaded_file)
                        time.sleep(0.5 * (2**attempt))
                        continue

                    raise ContentInvalid(f"Nội dung do AI sinh không đạt chuẩn: {reason}")

                except (AuthExpired, QuotaExceeded, ContentInvalid):
                    raise
                except Exception as exc:
                    err_str = str(exc)
                    code = getattr(exc, "code", None)
                    if code in (401, 403) or "API_KEY_INVALID" in err_str:
                        self._handle_api_error(exc)
                    if code == 429 or "RESOURCE_EXHAUSTED" in err_str:
                        self._handle_api_error(exc)

                    # Temporary server error (5xx or connection error) -> backoff retry
                    last_error = exc
                    if attempt < max_attempts - 1:
                        time.sleep(1.0 * (2**attempt))
                        continue
                    self._handle_api_error(exc)

            if last_error:
                self._handle_api_error(last_error)
            raise ContentInvalid("Không thể tạo nội dung sau nhiều lần thử.")

        finally:
            # Clean up uploaded file from Files API if any
            if uploaded_file is not None:
                try:
                    file_name = getattr(uploaded_file, "name", None)
                    if file_name:
                        client.files.delete(name=file_name)
                except Exception:
                    pass

