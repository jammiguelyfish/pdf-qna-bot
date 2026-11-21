"""Session-based auth endpoints for the single-page app.

These are plain Django views so Django's CSRF protection stays on for them:
the client first calls /csrf/ to receive the cookie, then sends it back in the
X-CSRFToken header, as for every other write.
"""
import json

from django.conf import settings
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


@require_POST
def login_view(request):
    data = _body(request)
    user = authenticate(
        request, username=str(data.get("username", "")), password=str(data.get("password", ""))
    )
    if user is None:
        return _error("Wrong username or password.", 401)
    login(request, user)
    return JsonResponse(_user_json(user))


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"detail": "ok"})
