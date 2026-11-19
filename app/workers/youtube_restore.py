"""Single-flight account restoration shared by startup worker entry points.

Only the first worker performs list_accounts (which restores accounts in order).
The other startup consumer waits for that snapshot without calling Google again.
Later explicit refreshes still perform a new list; mutations invalidate snapshots.
No credentials, HTTP clients or Qt widgets are kept here.
"""
from copy import deepcopy
from threading import Condition, RLock
from weakref import WeakKeyDictionary

from app.contracts import ChannelInfo
from app.errors import NetworkError
from app.services.youtube import auth

_REGISTRY = WeakKeyDictionary()
_REGISTRY_LOCK = RLock()


class _Snapshot:
    def __init__(self):
        self.condition = Condition(RLock())
        self.running = False
        self.ready = False
        self.consumers = set()
        self.result = None
        self.error = None
        self.generation = 0

    def get(self, service, consumer, token=None):
        with self.condition:
            waited = False
            while self.running:
                waited = True
                self.condition.wait(.1)
                if token is not None:
                    token.raise_if_cancelled()
            if self.ready and (waited or consumer not in self.consumers):
                self.consumers.add(consumer)
                if self.error is not None:
                    raise self.error
                return deepcopy(self.result)
            self.running = True
            self.ready = False
            self.consumers = {consumer}
            generation = self.generation
        result, error = None, None
        try:
            result = service.list_accounts()
        except BaseException as caught:
            error = caught
        finally:
            with self.condition:
                self.result, self.error = result, error
                self.running = False
                self.ready = generation == self.generation
                self.condition.notify_all()
        if error is not None:
            raise error
        return deepcopy(result)


def _snapshot(service):
    with _REGISTRY_LOCK:
        if service not in _REGISTRY:
            _REGISTRY[service] = _Snapshot()
        return _REGISTRY[service]


def fetch_accounts(service, *, consumer='fetch', token=None):
    return _snapshot(service).get(service, consumer, token)


def invalidate_accounts(service):
    state = _snapshot(service)
    with state.condition:
        state.generation += 1
        state.ready = False


def restored_default(accounts):
    """list_accounts already verified the grant; do not call get_channel again."""
    default = next((account for account in accounts if account.is_default), None)
    if default is None:
        return None
    if default.status == 'expired':
        raise auth.session_expired()
    if default.status != 'connected':
        raise NetworkError()
    return ChannelInfo(default.id, default.title)
