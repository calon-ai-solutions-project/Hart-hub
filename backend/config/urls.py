from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.listings.views import listing_photo


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/", include("apps.sourcing.api.urls")),
    path("api/", include("apps.accounts.api")),
    path("api/", include("apps.accounts.home")),
    path("api/", include("apps.chat.api.urls")),
    path("api/", include("apps.quotes.api")),
    path("api/", include("apps.listings.api")),
    path("api/", include("apps.enquiries.api")),
]
if settings.DEBUG:  # local development only: photos come from backend/media
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:  # car photos for signed-in staff, from the bucket
    urlpatterns.append(path("media/listings/<path:name>", listing_photo))
