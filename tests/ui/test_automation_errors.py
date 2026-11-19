"""User-facing diagnostics survive the interpreter/worker boundary."""
from types import SimpleNamespace
from app.services.gemini.automation import GeminiPromptInterpreter
from app.workers.automation_workers import InterpretPromptWorker


def capture(qapp, interpreter, prompt):
    messages = []
    worker = InterpretPromptWorker(interpreter, prompt)
    worker.signals.error.connect(messages.append)
    worker.run()
    assert len(messages) == 1
    return messages[0]


def test_missing_audience_is_actionable_before_any_api_request(qapp):
    interpreter = GeminiPromptInterpreter({}, {})
    message = capture(qapp, interpreter, 'Tải TikTok tạo nội dung AI rồi đăng YouTube')
    assert 'Hãy ghi rõ' in message
    assert 'trẻ em' in message


def test_http_400_survives_worker_without_raw_server_details(qapp):
    class ClientError(Exception):
        code = 400
    def generate(**kwargs):
        raise ClientError('api_key=private-value request payload')
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    interpreter = GeminiPromptInterpreter({'gemini_api_key': 'test-key'}, {'gemini_model': 'test-model'}, lambda key: client)
    message = capture(qapp, interpreter, 'Tải TikTok tạo nội dung AI rồi đăng YouTube, không dành cho trẻ em')
    assert 'HTTP 400' in message
    assert 'mô hình' in message
    assert 'private-value' not in message
    assert 'request payload' not in message
