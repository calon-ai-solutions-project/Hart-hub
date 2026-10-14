from django.http import Http404, HttpResponse
from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import public


class PublicCarView(APIView):
    """The public car page's data. No login: anyone with the link may open it, so it carries customer
    fields only and is rate limited."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def get(self, request, token):
        data = public.page(token)
        if data is None:
            return Response({"detail": "This link is not valid."}, status=404)
        response = Response(data)
        response["X-Robots-Tag"] = "noindex"
        response["Cache-Control"] = "no-store"
        return response


class PublicCarPhotoView(APIView):
    """One photo of a car on its public page, from the Hub's own address so nothing reveals where it is stored."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "public_photos"

    def get(self, request, token, position):
        found = public.photo(token, position, thumb=request.query_params.get("size") == "thumb")
        if found is None:
            raise Http404
        data, content_type = found
        response = HttpResponse(data, content_type=content_type)
        response["Cache-Control"] = "public, max-age=3600"
        response["X-Robots-Tag"] = "noindex"
        return response


urlpatterns = [
    path("public/cars/<str:token>", PublicCarView.as_view(), name="public-car"),
    path("public/cars/<str:token>/photos/<int:position>", PublicCarPhotoView.as_view(), name="public-car-photo"),
]
