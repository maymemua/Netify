"""Đăng nhập bằng một mật khẩu chung (VNSHOP_PASSWORD).

Không đặt VNSHOP_PASSWORD thì không cần đăng nhập (dùng trên máy cá nhân).
Đăng nhập đúng -> cookie ký HMAC, hết hạn sau COOKIE_DAYS ngày. Đổi mật khẩu là mọi
cookie cũ mất hiệu lực. Sai quá MAX_FAILURES lần trong FAILURE_WINDOW giây thì tạm khoá theo IP.
"""

import hashlib
import hmac
import html
import os
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "vnshop_session"
COOKIE_DAYS = 30
MAX_FAILURES = 5
FAILURE_WINDOW = 600
PUBLIC_PATHS = {"/login", "/logout", "/healthz", "/static/style.css"}

_failures = {}  # ip -> [thời điểm sai]


def password():
    return os.environ.get("VNSHOP_PASSWORD") or None


def _secret():
    extra = os.environ.get("VNSHOP_SECRET", "")
    return hashlib.sha256(f"vnshop-memory|{password()}|{extra}".encode()).digest()


def make_token(now=None):
    expires = int((now or time.time()) + COOKIE_DAYS * 86400)
    sig = hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def valid_token(token, now=None):
    try:
        expires, sig = token.split(".", 1)
        if int(expires) < (now or time.time()):
            return False
    except (AttributeError, ValueError):
        return False
    expected = hmac.new(_secret(), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def _client_ip(request):
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "?")


def _locked(ip, now):
    recent = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW]
    _failures[ip] = recent
    return len(recent) >= MAX_FAILURES


def _is_https(request):
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


LOGIN_PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>VNSHOP Memory</title><link rel="stylesheet" href="/static/style.css"></head>
<body><main class="login">
  <form method="post" action="/login" class="login-card">
    <h1>VNSHOP Memory</h1>
    <p class="muted">Tài liệu nội bộ. Nhập mật khẩu để tiếp tục.</p>
    {error}
    <label for="pw">Mật khẩu</label>
    <input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>
    <button class="primary wide" type="submit">Đăng nhập</button>
  </form>
</main></body></html>"""


def login_page(error=""):
    msg = f'<p class="login-error">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(LOGIN_PAGE.format(error=msg), status_code=401 if error else 200)


async def login(request: Request):
    now = time.time()
    ip = _client_ip(request)
    if _locked(ip, now):
        return login_page("Sai quá nhiều lần. Thử lại sau 10 phút.")
    form = await request.body()
    from urllib.parse import parse_qs
    given = (parse_qs(form.decode("utf-8", "replace")).get("password") or [""])[0]
    expected = password() or ""
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        _failures.setdefault(ip, []).append(now)
        return login_page("Mật khẩu không đúng.")
    _failures.pop(ip, None)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, make_token(now), max_age=COOKIE_DAYS * 86400, httponly=True,
                        samesite="lax", secure=_is_https(request))
    return response


def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


async def middleware(request: Request, call_next):
    if password() is None or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if valid_token(request.cookies.get(COOKIE, "")):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Cần đăng nhập"}, status_code=401)
    return RedirectResponse("/login", status_code=303)
