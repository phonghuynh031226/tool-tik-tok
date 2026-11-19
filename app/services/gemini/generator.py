"""Gemini AI Content Generator using official google-genai SDK."""

from __future__ import annotations

import concurrent.futures
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

# Use child logger of TikTokYouTubeStudio so logs pass through RedactingFilter in production
logger = logging.getLogger("TikTokYouTubeStudio.gemini")

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


class ModelUnavailable(ContentInvalid):
    """Only a model-generation 404 can trigger automatic model selection."""


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


def _extract_model_version(model_name: str) -> tuple[int, ...]:
    """Extract numeric version tuple from model name, e.g. 'gemini-3.1-flash-lite' -> (3, 1)."""
    match = re.search(r"(\d+(?:\.\d+)*)", model_name)
    if match:
        try:
            return tuple(int(p) for p in match.group(1).split("."))
        except ValueError:
            pass
    return (0,)


def select_preferred_model(
    models: list[str], saved_model: Optional[str] = None
) -> tuple[str, bool]:
    """Select preferred default model according to priority rules:
    - Never auto-select 'gemma' models.
    - Ignore models containing 'image' or 'imagen'.
    - Exclude models containing 'preview' or 'exp' from default selection (allow only if no stable model exists).
    - If saved_model is provided and exists in models, keep it (returns (saved_model, False)).
    - Highest priority: stable (non-preview, non-exp) 'flash-lite' / 'lite' models, ordered by highest version descending.
    - Next priority: stable (non-preview, non-exp) 'flash' models, ordered by highest version descending.
    - Next priority: other stable 'gemini' models, ordered by highest version descending.
    - Fallback: when no stable model is available, use preview/exp models ordered by flash-lite > flash > gemini, and report to user.
    """
    if not models:
        return "gemini-2.5-flash-lite", False

    # Filter out gemma and image models from automatic selection
    filtered = [
        m for m in models
        if "gemma" not in m.casefold() and "image" not in m.casefold()
    ]
    candidate_pool = filtered if filtered else list(models)

    # If saved_model is valid and still in models list, respect it
    if saved_model and saved_model in models:
        return saved_model, False

    stable_pool = [
        m for m in candidate_pool
        if "preview" not in m.casefold() and "exp" not in m.casefold()
    ]

    is_preview_fallback = False
    if stable_pool:
        active_pool = stable_pool
    else:
        active_pool = candidate_pool
        is_preview_fallback = any("preview" in m.casefold() or "exp" in m.casefold() for m in active_pool)

    # Priority 1: flash-lite (or lite) with highest version number
    p1 = [
        m
        for m in active_pool
        if "flash" in m.casefold()
        and ("flash-lite" in m.casefold() or "lite" in m.casefold())
    ]
    if p1:
        p1.sort(key=_extract_model_version, reverse=True)
        chosen = p1[0]
    else:
        # Priority 2: other flash models with highest version number
        p2 = [
            m
            for m in active_pool
            if "flash" in m.casefold()
        ]
        if p2:
            p2.sort(key=_extract_model_version, reverse=True)
            chosen = p2[0]
        else:
            # Priority 3: other gemini models with highest version number
            p3 = [m for m in active_pool if "gemini" in m.casefold()]
            if p3:
                p3.sort(key=_extract_model_version, reverse=True)
                chosen = p3[0]
            else:
                chosen = active_pool[0]

    # Did we have a saved_model that is no longer present or did we fallback to preview?
    switched = bool((saved_model and saved_model not in models) or is_preview_fallback)
    return chosen, switched


def _extract_http_code(exc: Exception) -> Optional[int]:
    """Extract HTTP status code from exception if available."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    err_str = str(exc)
    match = re.search(r"\b(4\d\d|5\d\d)\b", err_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def is_retryable_error(exc: Exception) -> bool:
    """Check if error is retryable.
    Only network errors, 429 (rate limit), and 5xx (Google server error) are retryable.
    400, 401, 403, 404 and content validation errors MUST NOT be retried.
    """
    if isinstance(exc, (AuthExpired, ContentInvalid)):
        return False

    code = _extract_http_code(exc)
    if code in (400, 401, 403, 404):
        return False
    if code == 429 or (isinstance(code, int) and 500 <= code <= 599):
        return True

    err_str = str(exc).casefold()
    # Explicit non-retryable keywords
    if any(
        k in err_str
        for k in (
            "404",
            "not found",
            "not_found",
            "deprecated",
            "400",
            "invalid_argument",
            "schema",
            "401",
            "403",
            "api_key_invalid",
            "permission_denied",
            "unauthenticated",
        )
    ):
        return False

    # Retryable: network, connection, timeout, 5xx
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    if any(
        k in err_str
        for k in (
            "timeout",
            "connect",
            "connection",
            "network",
            "dns",
            "reset",
            "refused",
            "unavailable",
            "server error",
            "500",
            "502",
            "503",
            "504",
        )
    ):
        return True

    return False


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
        self._available_models: list[str] | None = None
        self.last_model_notice = ''
        self.last_successful_model = ''

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
        from google.genai import types
        return genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))

    def _handle_api_error(self, exc: Exception, model_name: str = "") -> None:
        """Map SDK errors to safe Vietnamese application exceptions and log details.
        Logs exception class, HTTP code, and model name.
        Does NOT log API keys, tokens, or sensitive payloads.
        """
        model_display = model_name or "mặc định"
        code = _extract_http_code(exc)
        err_str = str(exc)
        exc_type = type(exc).__name__

        # 1. 404: Model not found or deprecated
        if code == 404 or (
            code is None
            and (
                "not found" in err_str.lower()
                or "is not found" in err_str.lower()
            )
        ):
            logger.error(
                "Gemini API error: [%s] HTTP 404 - Model '%s' does not exist or deprecated",
                exc_type,
                model_display,
            )
            raise ModelUnavailable(
                f"Mô hình AI '{model_display}' không tồn tại hoặc đã ngừng hỗ trợ (mã 404). "
                f"Vui lòng vào Cài đặt để chọn lại mô hình Gemini khác."
            ) from exc

        # 2. 400: Invalid request or response schema / JSON not supported by model
        if code == 400 or (
            code is None
            and (
                "schema" in err_str.lower()
                or "invalid argument" in err_str.lower()
                or "invalid_argument" in err_str.lower()
            )
        ):
            logger.error(
                "Gemini API error: [%s] HTTP 400 - Invalid request / unsupported schema for model '%s'",
                exc_type,
                model_display,
            )
            raise ContentInvalid(
                f"Mô hình AI '{model_display}' không hỗ trợ định dạng dữ liệu có cấu trúc (JSON schema) hoặc yêu cầu không hợp lệ (mã 400). "
                f"Vui lòng chọn mô hình Gemini Flash thế hệ mới trong Cài đặt."
            ) from exc

        # 3. 401 / 403: Invalid API key or permission denied
        if code in (401, 403) or (
            code is None
            and (
                "api_key_invalid" in err_str.lower()
                or "permission_denied" in err_str.lower()
                or "unauthenticated" in err_str.lower()
            )
        ):
            logger.error(
                "Gemini API error: [%s] HTTP %s - Authentication or permission denied for model '%s'",
                exc_type,
                code or "401/403",
                model_display,
            )
            raise AuthExpired(
                f"Khóa API Gemini không hợp lệ hoặc không có quyền truy cập (mã {code or '401/403'}). "
                f"Vui lòng kiểm tra và cập nhật lại API Key trong Cài đặt."
            ) from exc

        # 4. 429: Quota exceeded / Rate limit
        if code == 429 or (
            code is None
            and (
                "resource_exhausted" in err_str.lower()
                or "quota" in err_str.lower()
                or "rate limit" in err_str.lower()
            )
        ):
            logger.warning(
                "Gemini API error: [%s] HTTP 429 - Quota or rate limit exceeded for model '%s'",
                exc_type,
                model_display,
            )
            raise QuotaExceeded(
                "Đã vượt quá hạn mức sử dụng Gemini (mã 429). "
                "Vui lòng chờ ít phút rồi thử lại hoặc nâng cấp gói hạn mức."
            ) from exc

        # 5. 5xx: Google server error
        if (isinstance(code, int) and 500 <= code <= 599) or (
            code is None and "server error" in err_str.lower()
        ):
            logger.error(
                "Gemini API error: [%s] HTTP %s - Google server internal error for model '%s'",
                exc_type,
                code,
                model_display,
            )
            raise NetworkError(
                f"Máy chủ Google Gemini đang gặp sự cố nội bộ (mã {code or 500}). "
                f"Vui lòng chờ ít phút và thử lại sau."
            ) from exc

        # 6. Timeout
        if isinstance(exc, TimeoutError) or "timeout" in err_str.lower():
            logger.error(
                "Gemini network error: [%s] Timeout for model '%s'",
                exc_type,
                model_display,
            )
            raise NetworkError(
                "Quá thời gian phản hồi từ máy chủ Google Gemini (timeout 60 giây). "
                "Vui lòng kiểm tra lại kết nối mạng hoặc thử lại sau."
            ) from exc

        # 7. Network / DNS / socket error
        if isinstance(exc, (ConnectionError, OSError)) or any(
            k in err_str.lower()
            for k in ("connection", "connect", "dns", "getaddrinfo", "network")
        ):
            logger.error(
                "Gemini network error: [%s] Network/DNS connection failure for model '%s'",
                exc_type,
                model_display,
            )
            raise NetworkError(
                "Không thể kết nối đến máy chủ Google Gemini do sự cố mạng. "
                "Vui lòng kiểm tra kết nối Internet và thử lại."
            ) from exc

        # Default fallback: report error without misleading network message
        logger.error(
            "Gemini unexpected error: [%s] HTTP %s - Model '%s'",
            exc_type,
            code,
            model_display,
        )
        raise ContentInvalid(
            f"Không thể tạo nội dung với mô hình '{model_display}' ({exc_type}): {err_str}"
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
            self._available_models = list(result)
            return result
        except AuthExpired:
            raise
        except Exception as exc:
            self._handle_api_error(exc, "")
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
            self._handle_api_error(exc, "")
            return False

    def generate(self, meta: VideoMeta, settings: Mapping[str, Any]) -> GeneratedContent:
        """Try at most three distinct models, switching ONLY after a 404."""
        self.last_model_notice = ''
        self.last_successful_model = ''
        saved = (self._settings_store.get('gemini_default_model') or self._settings_store.get('gemini_model')) if self._settings_store else None
        model = settings.get('model') or saved or select_preferred_model(self._available_models or [])[0]
        original = model
        tried = []
        deadline = time.monotonic() + float(settings.get('timeout', 60.0))
        while len(tried) < 3:
            tried.append(model)
            try:
                content = self._generate_one(meta, dict(settings) | {'model': model, 'timeout': max(0.001, deadline - time.monotonic())})
            except ModelUnavailable:
                if self._available_models is None:
                    self.list_models()
                remaining = [name for name in self._available_models or [] if name not in tried
                    and 'gemini' in name.casefold() and 'flash' in name.casefold()
                    and 'image' not in name.casefold() and 'gemma' not in name.casefold()]
                if len(tried) == 3 or not remaining:
                    raise ModelUnavailable(
                        f"Mô hình AI '{original}' không tồn tại hoặc đã ngừng hỗ trợ (404). "
                        f"Đã thử {len(tried)} model khả dụng nhưng chưa tạo được nội dung. "
                        'Vui lòng chọn model khác trong Cài đặt rồi thử lại.'
                    ) from None
                model = select_preferred_model(remaining)[0]
                continue
            self.last_successful_model = model
            if self._settings_store:
                self._settings_store.set('gemini_model', model)
            if len(tried) > 1:
                self.last_model_notice = f'Model {original} không khả dụng, đã chuyển sang model {model}.'
            return content
        raise AssertionError('Unreachable')

    def _generate_one(self, meta: VideoMeta, settings: Mapping[str, Any]) -> GeneratedContent:
        """Generate optimized YouTube Shorts metadata with validation, timeout, and retry."""
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

        # Timeout setting (default: 60s)
        timeout_seconds = float(settings.get("timeout", 60.0))
        deadline = time.monotonic() + timeout_seconds

        # Retry logic: retry only for network errors, 429, and 5xx (up to 3 attempts)
        max_attempts = 3
        last_error: Optional[Exception] = None

        try:
            for attempt in range(max_attempts):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.error(
                        "Gemini Generate timed out after %.1fs for model '%s'",
                        timeout_seconds,
                        model_name,
                    )
                    raise NetworkError(
                        f"Quá thời gian phản hồi từ máy chủ Google Gemini (timeout {int(timeout_seconds)} giây). "
                        f"Vui lòng kiểm tra lại kết nối mạng hoặc thử lại sau."
                    )

                try:
                    # Run SDK call with remaining timeout in worker thread
                    # Bound transport I/O and never wait for a hung SDK call on timeout.
                    config.http_options = types.HttpOptions(
                        timeout=max(1, int(remaining * 1000)),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    )
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    try:
                        future = executor.submit(
                            client.models.generate_content,
                            model=model_name,
                            contents=contents,
                            config=config,
                        )
                        try:
                            response = future.result(timeout=remaining)
                        except concurrent.futures.TimeoutError as te:
                            future.cancel()
                            raise TimeoutError(
                                f"Quá thời gian phản hồi từ máy chủ Google Gemini (timeout {int(timeout_seconds)} giây)."
                            ) from te
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)

                    raw_text = getattr(response, "text", "") or ""
                    try:
                        data = json.loads(raw_text)
                    except Exception as json_err:
                        if attempt < max_attempts - 1 and (deadline - time.monotonic()) > 2.0:
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
                    if attempt < max_attempts - 1 and (deadline - time.monotonic()) > 2.0:
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
                    # Non-retryable errors (400, 401, 403, 404, etc.) must fail immediately
                    if not is_retryable_error(exc):
                        self._handle_api_error(exc, model_name)

                    # Retryable error (network, 429, 5xx)
                    last_error = exc
                    remaining_after_error = deadline - time.monotonic()
                    if attempt < max_attempts - 1 and remaining_after_error > 2.0:
                        backoff = min(1.0 * (2**attempt), 4.0)
                        logger.warning(
                            "Gemini retryable error on attempt %d: [%s], retrying in %.1fs...",
                            attempt + 1,
                            type(exc).__name__,
                            backoff,
                        )
                        time.sleep(backoff)
                        continue
                    self._handle_api_error(exc, model_name)

            if last_error:
                self._handle_api_error(last_error, model_name)
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

