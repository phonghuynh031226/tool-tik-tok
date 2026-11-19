import json
from types import SimpleNamespace
import pytest

from app.core.automation import AutomationPolicy
from app.errors import AuthExpired, ContentInvalid, NetworkError, QuotaExceeded
from app.services.gemini.automation import GeminiPromptInterpreter

PROMPT = 'Tải video TikTok, dùng AI tạo nội dung và đăng YouTube công khai ngay, không dành cho trẻ em.'
POLICY = dict(privacy='public', made_for_kids=False, interval_minutes=None,
              start_hour=0, start_minute=0, content_instructions='Viết tiếng Việt')


def interpreter(payload=None, *, key='test-key', error=None):
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return SimpleNamespace(text=json.dumps(payload))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    result = GeminiPromptInterpreter({'gemini_api_key': key}, {'gemini_model': 'gemini-selected'}, lambda key: client)
    return result, calls


def test_real_sdk_request_shape_and_public_policy():
    item, calls = interpreter({'supported': True, 'policy': POLICY})
    policy = item.interpret(PROMPT)
    assert policy == AutomationPolicy(**POLICY)
    assert calls[0]['model'] == 'gemini-selected'
    assert calls[0]['contents'] == PROMPT
    assert calls[0]['config'].response_mime_type == 'application/json'
    assert calls[0]['config'].system_instruction


def test_hourly_rollover_policy():
    item, _ = interpreter({'supported': True, 'policy': POLICY | {'interval_minutes': 60}})
    policy = item.interpret(PROMPT + ' Hẹn công khai 00h, 01h tới 23h rồi sang ngày mới.')
    assert policy.interval_minutes == 60
    assert policy.privacy == 'private'


@pytest.mark.parametrize('payload', [
    {'supported': False, 'policy': None},
    {'supported': True, 'policy': POLICY | {'made_for_kids': 'false'}},
    {'supported': True, 'policy': POLICY | {'made_for_kids': True}},
    {'supported': True, 'policy': POLICY | {'interval_minutes': 0}},
    {'supported': True, 'policy': POLICY | {'extra_action': 'delete'}},
    {'supported': True, 'policy': POLICY | {'content_instructions': 'api_key=unsafe'}},
    {'supported': True, 'policy': None}, {},
])
def test_reject_invalid_unsupported_or_audience_inference(payload):
    item, _ = interpreter(payload)
    with pytest.raises(ContentInvalid):
        item.interpret(PROMPT)


def test_audience_and_secret_must_be_explicit_before_network():
    item, calls = interpreter({'supported': True, 'policy': POLICY})
    with pytest.raises(ContentInvalid, match='trẻ em'):
        item.interpret('Tải video TikTok dùng AI rồi đăng YouTube')
    with pytest.raises(ContentInvalid):
        item.interpret(PROMPT + ' api_key=unsafe')
    assert calls == []


def test_missing_key_and_network_error_are_safe():
    item, calls = interpreter(key='')
    with pytest.raises(AuthExpired):
        item.interpret(PROMPT)
    assert calls == []
    item, _ = interpreter(error=RuntimeError('payload api_key=private-value'))
    with pytest.raises(NetworkError) as error:
        item.interpret(PROMPT)
    assert 'private-value' not in str(error.value)


@pytest.mark.parametrize('choice', ['không phải dành cho trẻ em', 'không phải là video dành cho trẻ em', 'not made for kids', 'nonkids'])
def test_negative_audience_phrasing(choice):
    item, _ = interpreter({'supported': True, 'policy': POLICY})
    assert item.interpret('Tải TikTok dùng AI rồi đăng YouTube, ' + choice).made_for_kids is False


def test_installed_genai_sdk_transforms_schema_and_reaches_mock_transport():
    try:
        import httpx
    except ImportError:
        import httpx2 as httpx
    from google import genai
    from google.genai import types
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            'candidates': [{'content': {'role': 'model', 'parts': [
                {'text': json.dumps({'supported': True, 'policy': POLICY})}
            ]}, 'finishReason': 'STOP'}]
        })
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with genai.Client(api_key='mock-transport-only', http_options=types.HttpOptions(httpx_client=http)) as client:
            item = GeminiPromptInterpreter({'gemini_api_key': 'mock-transport-only'},
                {'gemini_model': 'gemini-2.5-flash-lite'}, lambda key: client)
            assert item.interpret(PROMPT) == AutomationPolicy(**POLICY)
    assert len(requests) == 1
    config = requests[0]['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    # JSON Schema keywords (additionalProperties/$defs) must not go through
    # the legacy responseSchema protocol, which rejects them with HTTP 400.
    assert 'responseSchema' not in config
    schema = config['responseJsonSchema']
    assert schema['additionalProperties'] is False
    assert schema['$defs']['_PolicyResponse']['additionalProperties'] is False
    assert set(schema['properties']) == {'supported', 'policy'}



@pytest.mark.parametrize('status,error_type', [
    (400, ContentInvalid), (401, AuthExpired), (403, AuthExpired),
    (404, ContentInvalid), (429, QuotaExceeded), (500, NetworkError),
])
def test_sdk_error_reports_only_class_and_numeric_status(status, error_type):
    from google.genai import errors
    sdk_error = errors.ClientError(status, {'error': {
        'code': status, 'message': 'private-prompt api_key=private-value'
    }})
    item, _ = interpreter(error=sdk_error)
    with pytest.raises(error_type) as captured:
        item.interpret(PROMPT)
    message = str(captured.value)
    assert 'ClientError' in message
    assert f'HTTP {status}' in message
    assert 'private-prompt' not in message
    assert 'private-value' not in message


def test_schema_conversion_failure_reports_safe_type_without_raw_payload():
    item, _ = interpreter(error=ValueError('unsupported schema; api_key=private-value'))
    with pytest.raises(ContentInvalid) as captured:
        item.interpret(PROMPT)
    assert 'ValueError' in str(captured.value)
    assert 'private-value' not in str(captured.value)


def test_installed_genai_http_failure_is_safe_and_reaches_mock_transport():
    try:
        import httpx
    except ImportError:
        import httpx2 as httpx
    from google import genai
    from google.genai import types
    requests = []
    def respond(request):
        requests.append(True)
        return httpx.Response(400, json={'error': {
            'code': 400, 'message': 'private-prompt api_key=private-value', 'status': 'INVALID_ARGUMENT'
        }})
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with genai.Client(api_key='mock-transport-only', http_options=types.HttpOptions(
            httpx_client=http, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            item = GeminiPromptInterpreter({'gemini_api_key': 'mock-transport-only'},
                {'gemini_model': 'gemini-2.5-flash-lite'}, lambda key: client)
            with pytest.raises(ContentInvalid) as captured:
                item.interpret(PROMPT)
    message = str(captured.value)
    assert len(requests) == 1
    assert 'ClientError, HTTP 400' in message
    assert 'private-prompt' not in message
    assert 'private-value' not in message
    assert 'mock-transport-only' not in message



def test_prompt_interpreter_uses_explicit_default_instead_of_transient_model():
    item,calls=interpreter({'supported':True,'policy':POLICY})
    item._settings['gemini_default_model']='gemini-preferred-default'
    item.interpret(PROMPT)
    assert calls[0]['model']=='gemini-preferred-default'
