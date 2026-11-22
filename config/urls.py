from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path


def healthz(request):
    return JsonResponse({"status": "ok"})


def spa(request, *args, **kwargs):
    """Serve the React app for client-side routes such as /chat."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise Http404
    return FileResponse(open(index, "rb"), content_type="text/html")


urlpatterns = [
    path("healthz/", healthz),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/documents/", include("documents.urls")),
    path("api/", include("chat.urls")),
]

if settings.FRONTEND_DIST:
    # Last, so it never shadows the routes above or real files (WhiteNoise runs first).
    urlpatterns.append(re_path(r"^(?!api/|admin/|static/|assets/|healthz/)[^.]*$", spa))
