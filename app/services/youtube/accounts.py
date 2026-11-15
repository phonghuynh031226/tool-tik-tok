"""Token namespaces and temporary OAuth staging; secrets never enter settings."""
from . import auth


class AccountTokenStore:
    def __init__(self, store, channel_id):
        self.store = store
        self.token_key = auth.account_token_key(channel_id)

    def _key(self, key):
        return self.token_key if key == auth.TOKEN_KEY else key

    def get(self, key):
        return self.store.get(self._key(key))

    def set(self, key, value):
        self.store.set(self._key(key), value)

    def delete(self, key):
        self.store.delete(self._key(key))


class PendingTokenStore:
    """Hold a new OAuth grant in memory until channels.list identifies its owner."""
    def __init__(self, store):
        self.store = store
        self.token = None

    def get(self, key):
        return self.token if key == auth.TOKEN_KEY else self.store.get(key)

    def set(self, key, value):
        if key == auth.TOKEN_KEY:
            self.token = value
        else:
            self.store.set(key, value)

    def delete(self, key):
        if key == auth.TOKEN_KEY:
            self.token = None
        else:
            self.store.delete(key)
