"""Deterministic native-free probes: no real network, browser or keyring."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import threading
import time
import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import httplib2
import pytest
from google.oauth2.credentials import Credentials

from app.contracts import ChannelAccount, ChannelInfo
from app.errors import NetworkError
from app.services.fakes import FakeSettingsStore
from app.services.youtube import auth, service
from app.workers.service_workers import FetchAccountsWorker, YouTubeRestoreWorker
from tests.services.test_youtube_service import CHANNEL, MemorySecrets
from tests.services.test_youtube_accounts import accounts, credentials as account_credentials, A, B


def credential():
    return Credentials(token='old-test-token', refresh_token='test-refresh',
        client_id='test-client', client_secret='test-secret', scopes=auth.SCOPES,
        token_uri='https://oauth2.googleapis.com/token', expiry=datetime(2020, 1, 1))


def test_same_account_requests_from_two_threads_never_reuse_http(monkeypatch):
    secrets = MemorySecrets()
    creds = credential()
    creds.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    auth.save_credentials(creds, secrets)
    observations, lock = [], threading.Lock()
    active, peak = 0, 0
    def fake_request(http, uri, **kwargs):
        nonlocal active, peak
        with lock:
            observations.append((threading.get_ident(), http))
            active += 1
            peak = max(peak, active)
        time.sleep(.02)
        with lock:
            active -= 1
        return httplib2.Response({'status': '200', 'content-type': 'application/json'}), json.dumps({
            'items': [{'id': CHANNEL, 'snippet': {'title': 'Mock channel'}}]}).encode()
    monkeypatch.setattr(httplib2.Http, 'request', fake_request)
    youtube = service.YouTubeService(secret_store=secrets, settings_store=FakeSettingsStore())
    youtube.connect()
    observations.clear()
    peak = 0
    start = threading.Barrier(2)
    def query():
        start.wait(timeout=2)
        return youtube.get_channel()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: query(), range(2)))
    assert all(result.id == CHANNEL for result in results)
    threads = {thread for thread, _ in observations}
    transports = {id(http) for _, http in observations}
    print(f'caller_threads={len(threads)} http_objects={len(transports)} peak_api_calls={peak}')
    assert len(threads) == 2
    assert len(transports) == 2  # Fails before fix: facade lock serializes, but HTTP crosses threads.
    assert peak == 1  # Existing facade serialization is retained.


def test_startup_workers_coalesce_into_one_sequential_account_restore():
    lock = threading.Lock()
    entered, overlap = threading.Event(), threading.Event()
    calls, active, peak = 0, 0, 0
    class Probe:
        def list_accounts(self):
            nonlocal calls, active, peak
            with lock:
                calls += 1
                active += 1
                peak = max(peak, active)
                if active == 2:
                    overlap.set()
            entered.set()
            overlap.wait(.1)
            with lock:
                active -= 1
            return [ChannelAccount(CHANNEL, 'Mock channel', is_default=True)]
        def restore_session(self):
            return ChannelInfo(CHANNEL, 'Mock channel')
    backend = Probe()
    first, second = FetchAccountsWorker(backend), YouTubeRestoreWorker(backend)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first.run)
        assert entered.wait(2)
        b = pool.submit(second.run)
        a.result(timeout=3)
        b.result(timeout=3)
    print(f'startup_list_calls={calls} peak_list_calls={peak}')
    assert calls == 1 and peak == 1


def test_refresh_single_flight_for_separate_expired_copies(monkeypatch):
    secrets = MemorySecrets()
    auth.save_credentials(credential(), secrets)
    copies = [auth.load_credentials(secrets), auth.load_credentials(secrets)]
    calls = []
    def refresh(creds, request):
        calls.append(threading.get_ident())
        time.sleep(.03)
        creds.token = 'new-test-token'
        creds.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    monkeypatch.setattr(Credentials, 'refresh', refresh)
    start = threading.Barrier(2)
    def run(creds):
        start.wait(timeout=2)
        return auth.refresh_credentials(creds, secrets)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, copies))
    assert len(calls) == 1
    assert all((result or copy).valid for result, copy in zip(results, copies))


def test_lost_network_becomes_vietnamese_worker_error(monkeypatch, qtbot):
    monkeypatch.setattr(service, 'wait_backoff', Mock())
    owner = Mock(_credentials=Mock(valid=True, expired=False))
    operation = Mock(side_effect=ConnectionResetError('private-provider-diagnostic'))
    backend = Mock()
    backend.list_accounts.side_effect = lambda: service._Policy(owner, __import__('app.core.cancel', fromlist=['CancelToken']).CancelToken()).call(operation)
    worker = FetchAccountsWorker(backend)
    messages = []
    worker.signals.error.connect(messages.append)
    worker.run()
    assert messages and messages[0] == NetworkError().user_message
    assert 'private-provider' not in messages[0]


def test_truly_overlapping_transport_calls_own_and_close_distinct_http(monkeypatch):
    clients = []
    entered = threading.Barrier(2)
    class Http:
        def __init__(self, *, timeout):
            self.timeout, self.closed = timeout, False
            self.redirect_codes = {301, 302, 303, 307, 308}
            clients.append(self)
        def request(self, *args, **kwargs):
            assert not self.closed and self.follow_redirects is False
            assert kwargs['redirections'] == 0 and 308 not in self.redirect_codes
            entered.wait(timeout=2)
            return httplib2.Response({'status': '200'}), b'{}'
        def close(self):
            self.closed = True
    monkeypatch.setattr(service.httplib2, 'Http', Http)
    transport = service._Transport(SimpleNamespace(_credentials=credential()))
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: transport.request('https://www.googleapis.com/youtube/v3/channels'), range(2)))
    assert len(replies) == 2 and len(clients) == 2
    assert clients[0] is not clients[1]
    assert all(client.timeout == 30 and client.closed for client in clients)


@pytest.mark.parametrize('error', [TimeoutError('private timeout'), OSError('private socket'), ssl.SSLEOFError('private TLS read')])
def test_connect_read_and_ssl_errors_are_bounded_network_errors(monkeypatch, error):
    monkeypatch.setattr(service, 'wait_backoff', Mock())
    operation = Mock(side_effect=error)
    owner = SimpleNamespace(_credentials=Mock(expired=False, valid=True))
    with pytest.raises(NetworkError) as caught:
        service._Policy(owner, __import__('app.core.cancel', fromlist=['CancelToken']).CancelToken()).call(operation)
    assert operation.call_count == 6
    assert 'private' not in caught.value.user_message


def test_refresh_sets_explicit_connect_and_read_timeouts(monkeypatch):
    secrets = MemorySecrets()
    creds = credential()
    auth.save_credentials(creds, secrets)
    request = Mock()
    monkeypatch.setattr(auth, 'Request', Mock(return_value=request))
    def refresh(creds, transport):
        transport(url='https://oauth2.googleapis.com/token', method='POST')
        creds.token = 'new-test-token'
        creds.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    monkeypatch.setattr(Credentials, 'refresh', refresh)
    auth.refresh_credentials(creds, secrets)
    assert request.call_args.kwargs['timeout'] == (10, 30)


def test_each_account_is_verified_once_in_a_restore_pass(accounts):
    youtube, _, _, authorized, clients, _ = accounts
    authorized.extend([account_credentials(A), account_credentials(B)])
    youtube.add_account()
    youtube.add_account()
    result = youtube.list_accounts()
    assert len(result) == 2 and all(account.status == 'connected' for account in result)
    assert [clients[channel][0].channels.return_value.list.call_count for channel in (A, B)] == [1, 1]
