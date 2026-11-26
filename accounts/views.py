"""Session-based auth endpoints for the single-page app.

These are plain Django views so Django's CSRF protection stays on for them:
the client first calls /csrf/ to receive the cookie, then sends it back in the
X-CSRFToken header, as for every other write.
"""
import json

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import authenticate, get_user_model, login, logout, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

User = get_user_model()


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _user_json(user) -> dict:
    return {"id": user.pk, "username": user.get_username()}


def _error(message, status=400, **extra):
    return JsonResponse({"detail": message, **extra}, status=status)


@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"detail": "ok"})


@require_GET
def me(request):
    if not request.user.is_authenticated:
        return _error("Not signed in.", 401)
    return JsonResponse(_user_json(request.user))


@require_POST
def register(request):
    if not settings.ALLOW_REGISTRATION:
        return _error("Sign-up is disabled on this server.", 403)
    data = _body(request)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not 3 <= len(username) <= 150:
        return _error("Choose a username between 3 and 150 characters.")
    if User.objects.filter(username__iexact=username).exists():
        return _error("That username is taken.", 409)
    try:
        password_validation.validate_password(password, User(username=username))
    except ValidationError as exc:
        return _error(" ".join(exc.messages), passwords=list(exc.messages))
    try:
        user = User.objects.create_user(username=username, password=password)
    except IntegrityError:  # lost a race with another sign-up
        return _error("That username is taken.", 409)
    login(request, user)
    return JsonResponse(_user_json(user), status=201)


def _client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "")


def _login_keys(request, username: str):
    """Failure counters: one per (address, username), one per address."""
    ip = _client_ip(request)
    return (
        (f"login-fail:{ip}:{username.lower()}", settings.LOGIN_MAX_FAILURES),
        (f"login-fail-ip:{ip}", settings.LOGIN_MAX_FAILURES_PER_IP),
    )


def _record_failure(key: str):
    # add() starts the window on the first failure; later failures do not extend it
    if cache.add(key, 1, settings.LOGIN_LOCKOUT_SECONDS):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.add(key, 1, settings.LOGIN_LOCKOUT_SECONDS)


@require_POST
def login_view(request):
    data = _body(request)
    username = str(data.get("username", ""))
    keys = _login_keys(request, username)
    if any(cache.get(key, 0) >= limit for key, limit in keys):
        response = _error("Too many failed sign-in attempts. Try again later.", 429)
        response["Retry-After"] = str(settings.LOGIN_LOCKOUT_SECONDS)
        return response
    user = authenticate(request, username=username, password=str(data.get("password", "")))
    if user is None:
        for key, _ in keys:
            _record_failure(key)
        return _error("Wrong username or password.", 401)
    cache.delete(keys[0][0])
    login(request, user)
    return JsonResponse(_user_json(user))


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"detail": "ok"})
