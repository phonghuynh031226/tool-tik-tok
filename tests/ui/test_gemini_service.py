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
    GeminiContentGenerator, validate_and_sanitize_content,
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

