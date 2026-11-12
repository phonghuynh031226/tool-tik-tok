from urllib.error import HTTPError
from unittest.mock import Mock

import pytest

from app.errors import DisallowedHost, InvalidUrl
from app.services.tiktok.url import extract_video_id, normalize_url, resolve_url, validate_url


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('urllib.request.OpenerDirector.open', Mock(side_effect=AssertionError('Network forbidden')))


@pytest.mark.parametrize('host', ['tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'])
def test_allowlisted_direct_urls(host):
    assert normalize_url(f'https://{host}/@demo/video/123?utm_source=test#x') == 'https://www.tiktok.com/@demo/video/123'
    assert extract_video_id(f'https://{host}/@demo/video/123') == '123'


def test_normalization():
    assert normalize_url(' HTTP://M.TIKTOK.COM:80/@demo/video/123/ ?x=1 '.replace('/ ?', '/?')) == 'https://www.tiktok.com/@demo/video/123'
    assert normalize_url('tiktok.com/share/video/123') == 'https://www.tiktok.com/@_/video/123'
    assert extract_video_id('https://www.tiktok.com/embed/v2/123') == '123'


@pytest.mark.parametrize('url', ['', 'abc', 'ftp://www.tiktok.com/@a/video/1', 'https://www.tiktok.com',
    'https://www.tiktok.com/@a/video/no', 'https://www.tiktok.com:444/@a/video/1',
    'https://user:pass@www.tiktok.com/@a/video/1', 'https://www.tiktok.com/@a/video/1/extra',
    'https://www.tiktok.com/@a/video/1\nfoo', 'https://www.tiktok.com\\@evil.test/@a/video/1'])
def test_invalid_url(url):
    with pytest.raises(InvalidUrl):
        normalize_url(url)


@pytest.mark.parametrize('host', ['evil.test', 'www.tiktok.com.evil.test', 'tiktok.com.', 'www.tiktokv.com', '127.0.0.1', 'tiktоk.com'])
def test_reject_unknown_host(host):
    with pytest.raises(DisallowedHost):
        validate_url(f'https://{host}/@a/video/123')


@pytest.mark.parametrize('path', ['/@a/photo/123', '/@a/%70hoto/123'])
def test_photo_post_has_clear_message(path):
    with pytest.raises(InvalidUrl) as caught:
        normalize_url('https://www.tiktok.com' + path)
    assert 'slideshow' in caught.value.user_message.lower()
    assert not caught.value.retryable


def test_short_link_is_not_mistaken_for_video_id():
    with pytest.raises(InvalidUrl):
        extract_video_id('https://vm.tiktok.com/Zabc123/')


def test_redirects_are_manual_and_queries_removed():
    request = Mock(side_effect=[(302, 'https://vt.tiktok.com/Znext/?tracking=1'),
                                (301, 'https://m.tiktok.com/@demo/video/123?x=1'), (200, None)])
    assert resolve_url('https://vm.tiktok.com/Zstart/?x=1', request_redirect=request) == 'https://www.tiktok.com/@demo/video/123'
    assert [call.args[0] for call in request.call_args_list] == [
        'https://vm.tiktok.com/Zstart/', 'https://vt.tiktok.com/Znext/', 'https://m.tiktok.com/@demo/video/123']


def test_redirect_outside_allowlist_is_never_requested():
    request = Mock(return_value=(302, 'https://evil.test/steal'))
    with pytest.raises(DisallowedHost):
        resolve_url('https://vm.tiktok.com/Zstart/', request_redirect=request)
    assert request.call_count == 1


def test_relative_redirect_and_five_hop_limit():
    request = Mock(side_effect=[(302, f'/Z{i}/') for i in range(5)] + [(200, None)])
    with pytest.raises(InvalidUrl):  # Final page still has no video id.
        resolve_url('https://vm.tiktok.com/Zstart/', request_redirect=request)
    assert request.call_count == 6
    request = Mock(side_effect=[(302, f'/Z{i}/') for i in range(6)])
    with pytest.raises(InvalidUrl) as caught:
        resolve_url('https://vm.tiktok.com/Zstart/', request_redirect=request)
    assert '5' in caught.value.user_message
    assert request.call_count == 6


def test_five_redirects_to_video_are_accepted():
    request = Mock(side_effect=[(302, f'/Z{i}/') for i in range(4)] +
                    [(302, 'https://www.tiktok.com/@a/video/123'), (200, None)])
    assert resolve_url('https://vm.tiktok.com/Zstart/', request_redirect=request).endswith('/video/123')


def test_redirect_loop_and_photo_are_rejected():
    for target in ['https://vm.tiktok.com/Zstart/', 'https://www.tiktok.com/@a/photo/123']:
        request = Mock(return_value=(302, target))
        with pytest.raises(InvalidUrl):
            resolve_url('https://vm.tiktok.com/Zstart/', request_redirect=request)
        assert request.call_count == 1


def test_real_resolver_disables_automatic_redirects(monkeypatch):
    from app.services.tiktok import url as module
    opener = Mock()
    response = Mock(status=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    redirect = HTTPError('https://vm.tiktok.com/Zstart/', 302, 'Found',
                         {'Location': 'https://www.tiktok.com/@a/video/123'}, None)
    opener.open.side_effect = [redirect, response]
    build = Mock(return_value=opener)
    monkeypatch.setattr(module, 'build_opener', build)
    assert resolve_url('https://vm.tiktok.com/Zstart/').endswith('/video/123')
    handler = next(arg for arg in build.call_args.args if hasattr(arg, 'redirect_request'))
    assert handler.redirect_request(None, None, 302, 'Found', {}, 'https://evil.test') is None
