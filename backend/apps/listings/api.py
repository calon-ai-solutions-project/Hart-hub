from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanSell, CanView
from apps.core.services import emit_event

from .models import Listing, ListingPhoto
from .services import public


def staff_photo_json(photo):
    damage = public.is_damage(photo.label)
    file = photo.thumbnail or photo.image
    return {"position": photo.position, "label": photo.label, "damage": damage, "hidden": photo.hidden,
            "shown_to_customers": bool(photo.image) and not damage and not photo.hidden,
            "url": f"{settings.MEDIA_URL}{file.name}" if file else "",
            "full_url": f"{settings.MEDIA_URL}{photo.image.name}" if photo.image else ""}


class ListingPhotosView(APIView):
    """Staff: every photo of a car, and which ones customers see."""

    permission_classes = [CanView]

    def get(self, request, listing_id):
        listing = get_object_or_404(Listing, pk=listing_id)
        photos = list(listing.photos.order_by("position"))
        return Response({"photos": [staff_photo_json(p) for p in photos],
                         "shown": sum(staff_photo_json(p)["shown_to_customers"] for p in photos)})


class PhotoVisibility(serializers.Serializer):
    hidden = serializers.BooleanField()


class ListingPhotoView(APIView):
    """Staff: hide a photo from customers, or show it again. A damage photo always stays hidden."""

    permission_classes = [CanSell]

    def patch(self, request, listing_id, position):
        photo = get_object_or_404(ListingPhoto, listing_id=listing_id, position=position)
        serializer = PhotoVisibility(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo.hidden = serializer.validated_data["hidden"]
        photo.save(update_fields=["hidden"])
        emit_event("listing.photo_hidden" if photo.hidden else "listing.photo_shown",
                   {"listing_id": str(listing_id), "position": position}, actor=request.user)
        return Response(staff_photo_json(photo))


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
    path("listings/<uuid:listing_id>/photos", ListingPhotosView.as_view()),
    path("listings/<uuid:listing_id>/photos/<int:position>", ListingPhotoView.as_view()),
    path("public/cars/<str:token>", PublicCarView.as_view(), name="public-car"),
    path("public/cars/<str:token>/photos/<int:position>", PublicCarPhotoView.as_view(), name="public-car-photo"),
]
