from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/", include("apps.sourcing.api.urls")),
]
