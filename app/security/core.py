import hmac
import secrets
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer


class Security:
    def __init__(self, settings):
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(settings.secret_key, salt="session")
        self.failures = {}

    def verify(self, u, p, client="unknown"):
        count, last = self.failures.get(client, (0, 0))
        delay = min(count * 0.15, 2)
        if delay and time.monotonic() - last < delay:
            time.sleep(delay - (time.monotonic() - last))
        ok = hmac.compare_digest(u, self.settings.admin_username) and hmac.compare_digest(
            p, self.settings.admin_password
        )
        if ok:
            self.failures.pop(client, None)
        else:
            self.failures[client] = (min(count + 1, 20), time.monotonic())
        return ok

    def new_session(self):
        return self.serializer.dumps({"admin": True, "csrf": secrets.token_urlsafe(32)})

    def load(self, value):
        try:
            return self.serializer.loads(value, max_age=self.settings.session_max_age_seconds)
        except (BadSignature, TypeError):
            return None
