"""Comprehensive unit tests for GeminiContentGenerator using mocks (no network)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from google.genai import errors

from app.contracts import GeneratedContent, VideoMeta
from app.errors import AuthExpired, ContentInvalid, NetworkError, QuotaExceeded
from app.services.fakes import FakeSecretStore, FakeSettingsStore
from app.services.gemini.generator import (
    GeminiContentGenerator, select_preferred_model,
    validate_and_sanitize_content,
)


@pytest.fixture
def sample_meta():
    return VideoMeta(
        video_id="tiktok-123",
        url="https://tiktok.com/@creator/video/123",
        title="Tiêu đề mẫu từ TikTok",
        description="Mô tả gốc ngắn gọn",
        author="@creator",
        thumbnail_url=None,
        duration=30.0,
        width=1080,
        height=1920,
    )


def test_validation_and_sanitizing():
    # 1. Normal content
    ok, reason, content = validate_and_sanitize_content(
        title="Tiêu đề chuẩn",
        description="Mô tả chi tiết",
        hashtags=["#shorts", "#trend"],
        tags=["tiktok", "video"],
    )
    assert ok
    assert content.title == "Tiêu đề chuẩn"
    assert content.hashtags == ["shorts", "trend"]  # # stripped
    assert content.tags == ["tiktok", "video"]

    # 2. Content with < and > prohibited characters
    ok, reason, content = validate_and_sanitize_content(
        title="Tiêu đề <có thẻ>",
        description="Mô tả <script>alert(1)</script>",
        hashtags=["<tag1>"],
        tags=["<tag2>"],
    )
    assert ok
    assert "<" not in content.title and ">" not in content.title
    assert "<" not in content.description and ">" not in content.description
    assert content.title == "Tiêu đề có thẻ"

    # 3. Title exceeding 100 characters gets trimmed
    long_title = "A" * 120
    ok, reason, content = validate_and_sanitize_content(
        title=long_title,
        description="Mô tả",
        hashtags=[],
        tags=[],
    )
    assert ok
    assert len(content.title) <= 100

    # 4. Description exceeding 5000 bytes UTF-8 gets trimmed
    long_desc = "Từ tiếng Việt có dấu dài " * 250
    assert len(long_desc.encode("utf-8")) > 5000
    ok, reason, content = validate_and_sanitize_content(
        title="Tiêu đề",
        description=long_desc,
        hashtags=[],
        tags=[],
    )
    assert ok
    assert len(content.description.encode("utf-8")) <= 5000

    # 5. Total tags exceeding 500 characters get trimmed
    many_tags = [f"tag_item_number_{i}" for i in range(50)]
    assert sum(len(t) for t in many_tags) > 500
    ok, reason, content = validate_and_sanitize_content(
        title="Tiêu đề",
        description="Mô tả",
        hashtags=[],
        tags=many_tags,
    )
    assert ok
    assert sum(len(t) for t in content.tags) <= 500


def test_list_models_filters_generate_content():
    mock_client = MagicMock()

    m1 = MagicMock()
    m1.name = "models/gemini-2.5-flash"
    m1.supported_actions = ["generateContent"]

    m2 = MagicMock()
    m2.name = "models/text-embedding-004"
    m2.supported_actions = ["embedContent"]

    m3 = MagicMock()
    m3.name = "models/gemini-1.5-pro"
    m3.supported_actions = ["generateContent", "countTokens"]

    mock_client.models.list.return_value = [m1, m2, m3]

    generator = GeminiContentGenerator(
        api_key="mock-key",
        client_factory=lambda _: mock_client,
    )
    models = generator.list_models()

    assert models == ["gemini-2.5-flash", "gemini-1.5-pro"]
    assert "text-embedding-004" not in models


def test_test_connection_success_and_failure():
    mock_client = MagicMock()
    mock_client.models.list.return_value = [MagicMock()]

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )
    assert generator.test_connection() is True

    # Missing API key raises AuthExpired
    generator_no_key = GeminiContentGenerator(
        api_key="",
        client_factory=lambda _: mock_client,
    )
    with pytest.raises(AuthExpired) as exc_info:
        generator_no_key.test_connection()
    assert "Chưa cấu hình khóa API" in str(exc_info.value)


def test_generate_valid_structured_json(sample_meta):
    mock_client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "Bí quyết làm video Shorts triệu view",
        "description": "Hướng dẫn chi tiết từ A-Z tối ưu video.",
        "hashtags": ["shorts", "trending"],
        "tags": ["video", "huong dan"],
    })
    mock_client.models.generate_content.return_value = mock_response

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    result = generator.generate(sample_meta, settings={"model": "gemini-2.0-flash"})
    assert isinstance(result, GeneratedContent)
    assert result.title == "Bí quyết làm video Shorts triệu view"
    assert result.hashtags == ["shorts", "trending"]
    assert result.tags == ["video", "huong dan"]


def test_generate_malformed_json_retries_and_raises(sample_meta):
    mock_client = MagicMock()
    bad_response = MagicMock()
    bad_response.text = "NOT_A_JSON_STRING"
    mock_client.models.generate_content.return_value = bad_response

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(ContentInvalid) as exc:
        generator.generate(sample_meta, settings={})

    assert "JSON" in str(exc.value)
    # Ensure it tried retrying (max_attempts = 3)
    assert mock_client.models.generate_content.call_count == 3


def test_generate_rate_limit_raises_quota_exceeded(sample_meta):
    mock_client = MagicMock()
    err_429 = errors.APIError(429, {"error": {"message": "Resource exhausted"}})
    mock_client.models.generate_content.side_effect = err_429

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(QuotaExceeded) as exc:
        generator.generate(sample_meta, settings={})

    assert "hạn mức" in exc.value.user_message


def test_generate_invalid_key_raises_auth_expired(sample_meta):
    mock_client = MagicMock()
    err_401 = errors.APIError(401, {"error": {"message": "API_KEY_INVALID"}})
    mock_client.models.generate_content.side_effect = err_401

    generator = GeminiContentGenerator(
        api_key="bad-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(AuthExpired) as exc:
        generator.generate(sample_meta, settings={})

    assert "không hợp lệ" in str(exc.value)


def test_generate_transient_error_retries_with_backoff(sample_meta):
    mock_client = MagicMock()

    # Fail twice with 503, succeed on 3rd attempt
    err_503 = errors.APIError(503, {"error": {"message": "Service unavailable"}})
    good_response = MagicMock()
    good_response.text = json.dumps({
        "title": "Tiêu đề thành công sau retry",
        "description": "Mô tả",
        "hashtags": ["demo"],
        "tags": ["test"],
    })

    mock_client.models.generate_content.side_effect = [err_503, err_503, good_response]

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with patch("time.sleep") as mock_sleep:
        res = generator.generate(sample_meta, settings={})
        assert res.title == "Tiêu đề thành công sau retry"
        assert mock_client.models.generate_content.call_count == 3
        assert mock_sleep.call_count == 2


def test_files_api_flag_behavior(sample_meta, tmp_path):
    mock_client = MagicMock()

    uploaded_mock = MagicMock()
    uploaded_mock.name = "files/test-video-id"
    mock_client.files.upload.return_value = uploaded_mock

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "Tiêu đề dựa trên video thực tế",
        "description": "Mô tả dựa trên video",
        "hashtags": ["shorts"],
        "tags": ["video"],
    })
    mock_client.models.generate_content.return_value = mock_response

    fake_video = tmp_path / "sample.mp4"
    fake_video.write_bytes(b"dummy mp4 content")

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    # 1. When analyze_video_file is False (default) -> files.upload is NOT called
    generator.generate(sample_meta, settings={"video_path": str(fake_video), "analyze_video_file": False})
    mock_client.files.upload.assert_not_called()

    # 2. When analyze_video_file is True -> files.upload IS called, and cleaned up via files.delete
    generator.generate(sample_meta, settings={"video_path": str(fake_video), "analyze_video_file": True})
    mock_client.files.upload.assert_called_once_with(file=str(fake_video))
    mock_client.files.delete.assert_called_once_with(name="files/test-video-id")


def test_error_404_model_not_found_no_retry(sample_meta):
    """Test that HTTP 404 (model not found) fails immediately without retrying."""
    mock_client = MagicMock()
    err_404 = errors.APIError(404, {"error": {"message": "models/gemini-deprecated is not found"}})
    mock_client.models.generate_content.side_effect = err_404

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(ContentInvalid) as exc:
        generator.generate(sample_meta, settings={"model": "gemini-deprecated"})

    msg = str(exc.value)
    assert "404" in msg
    assert "không tồn tại hoặc đã ngừng hỗ trợ" in msg
    assert "gemini-deprecated" in msg
    # Crucial: Must NOT retry 404! Exactly 1 call
    assert mock_client.models.generate_content.call_count == 1


def test_error_400_invalid_argument_no_retry(sample_meta):
    """Test that HTTP 400 (invalid request / schema unsupported) fails immediately without retrying."""
    mock_client = MagicMock()
    err_400 = errors.APIError(400, {"error": {"message": "response_schema is not supported for this model"}})
    mock_client.models.generate_content.side_effect = err_400

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(ContentInvalid) as exc:
        generator.generate(sample_meta, settings={"model": "gemini-custom"})

    msg = str(exc.value)
    assert "400" in msg
    assert "JSON schema" in msg or "không hỗ trợ" in msg
    assert "gemini-custom" in msg
    # Must NOT retry 400! Exactly 1 call
    assert mock_client.models.generate_content.call_count == 1


def test_error_401_403_permission_denied_no_retry(sample_meta):
    """Test that HTTP 403 (permission denied) fails immediately without retrying."""
    mock_client = MagicMock()
    err_403 = errors.APIError(403, {"error": {"message": "PERMISSION_DENIED: The caller does not have permission"}})
    mock_client.models.generate_content.side_effect = err_403

    generator = GeminiContentGenerator(
        api_key="forbidden-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(AuthExpired) as exc:
        generator.generate(sample_meta, settings={})

    msg = str(exc.value)
    assert "403" in msg or "quyền truy cập" in msg
    assert mock_client.models.generate_content.call_count == 1


def test_error_429_quota_exceeded_retries_and_raises(sample_meta):
    """Test that HTTP 429 retries with backoff and raises QuotaExceeded."""
    mock_client = MagicMock()
    err_429 = errors.APIError(429, {"error": {"message": "RESOURCE_EXHAUSTED: quota exceeded"}})
    mock_client.models.generate_content.side_effect = err_429

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(QuotaExceeded) as exc:
            generator.generate(sample_meta, settings={})

    msg = str(exc.value)
    assert "429" in msg or "hạn mức" in msg
    assert mock_client.models.generate_content.call_count == 3
    assert mock_sleep.call_count == 2


def test_error_5xx_server_error_retries_and_raises(sample_meta):
    """Test that HTTP 500 retries with backoff and raises NetworkError."""
    mock_client = MagicMock()
    err_500 = errors.APIError(500, {"error": {"message": "Internal server error"}})
    mock_client.models.generate_content.side_effect = err_500

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(NetworkError) as exc:
            generator.generate(sample_meta, settings={})

    msg = str(exc.value)
    assert "500" in msg
    assert "sự cố nội bộ" in msg
    assert mock_client.models.generate_content.call_count == 3
    assert mock_sleep.call_count == 2


def test_error_network_connection_retries_and_raises(sample_meta):
    """Test that genuine network/DNS failure retries and raises NetworkError."""
    mock_client = MagicMock()
    conn_err = ConnectionError("Failed to establish connection: [Errno 11001] getaddrinfo failed")
    mock_client.models.generate_content.side_effect = conn_err

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(NetworkError) as exc:
            generator.generate(sample_meta, settings={})

    msg = str(exc.value)
    assert "sự cố mạng" in msg or "kết nối" in msg
    assert mock_client.models.generate_content.call_count == 3
    assert mock_sleep.call_count == 2


def test_generate_timeout_60s(sample_meta):
    """Test that timeout (e.g. 60s) raises NetworkError with timeout message."""
    mock_client = MagicMock()

    import time
    def slow_generate(*args, **kwargs):
        time.sleep(0.5)
        return MagicMock()

    mock_client.models.generate_content.side_effect = slow_generate

    generator = GeminiContentGenerator(
        api_key="valid-key",
        client_factory=lambda _: mock_client,
    )

    with pytest.raises(NetworkError) as exc:
        # Pass a small timeout for fast unit testing
        generator.generate(sample_meta, settings={"timeout": 0.1})

    msg = str(exc.value)
    assert "timeout" in msg.lower() or "quá thời gian" in msg.lower()


def test_select_preferred_model():
    """Test priority selection of default models and handling of missing saved models."""
    # 1. Prioritize highest version flash-lite when multiple are available, ignore gemma and image
    models = [
        "gemma-7b-it",
        "imagen-3.0-generate",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.0-flash-lite",
    ]
    chosen, switched = select_preferred_model(models)
    assert chosen == "gemini-3.1-flash-lite"
    assert switched is False

    # 2. Prioritize flash with highest version when flash-lite is not available
    models_no_lite = ["gemma-2-9b", "imagen-3.0", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"]
    chosen, switched = select_preferred_model(models_no_lite)
    assert chosen == "gemini-2.0-flash"
    assert switched is False

    # 3. Gemma and image models are never auto-selected if another model is available
    models_with_gemma_image = ["gemma-2-27b", "image-preview-01", "gemini-1.5-pro"]
    chosen, switched = select_preferred_model(models_with_gemma_image)
    assert chosen == "gemini-1.5-pro"
    assert "gemma" not in chosen
    assert "image" not in chosen

    # 4. Respect saved model if still present in models list
    chosen, switched = select_preferred_model(
        ["gemini-2.0-flash", "gemini-1.5-pro"],
        saved_model="gemini-1.5-pro",
    )
    assert chosen == "gemini-1.5-pro"
    assert switched is False

    # 5. When saved model is deprecated/missing, switch to preferred and signal switched=True
    chosen, switched = select_preferred_model(
        ["gemini-2.0-flash", "gemini-1.5-pro"],
        saved_model="gemini-1.0-pro",
    )
    assert chosen == "gemini-2.0-flash"
    assert switched is True


