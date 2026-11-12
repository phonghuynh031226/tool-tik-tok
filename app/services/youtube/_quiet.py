"""Suppress SDK wire/auth diagnostics which may include credential payloads."""

from contextlib import contextmanager
import logging

_PREFIXES = ('google_auth_oauthlib', 'google.auth', 'google.oauth2', 'googleapiclient',
             'oauthlib', 'requests_oauthlib', 'urllib3', 'requests', 'httplib2')


class _DropSDK(logging.Filter):
    def filter(self, record):
        return not record.name.startswith(_PREFIXES)


@contextmanager
def quiet_sdk():
    guard = _DropSDK()
    targets = {handler for logger in [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
               if isinstance(logger, logging.Logger) for handler in logger.handlers}
    targets.update(logger for name, logger in logging.Logger.manager.loggerDict.copy().items()
                   if name.startswith(_PREFIXES) and isinstance(logger, logging.Logger))
    for target in targets:
        target.addFilter(guard)
    try:
        yield
    finally:
        for target in targets:
            target.removeFilter(guard)
