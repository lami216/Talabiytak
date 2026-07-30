from fastapi import Request
from fastapi.responses import RedirectResponse


def session_data(request):
    return request.app.state.security.load(
        request.cookies.get(request.app.state.settings.session_cookie_name)
    )


def require_admin(request: Request):
    data = session_data(request)
    if not data:
        return RedirectResponse("/login", 303)
    return data


def csrf_ok(request, token):
    data = session_data(request)
    return bool(data and token and __import__("hmac").compare_digest(data.get("csrf", ""), token))
