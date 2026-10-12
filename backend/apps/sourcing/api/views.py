import hmac

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.services import get_setting
from apps.listings.models import Listing
from apps.listings.services.expiry import expire_listings
from apps.listings.services.photos import InvalidPhoto, missing_positions, store_photo
from apps.listings.tasks import make_thumbnail

from ..models import SyncRun
from ..platforms import PLATFORMS
from ..services import runs
from ..services.alerts import UnknownPlatform, ingest_alert
from ..services.ingest import IngestError, save_scraped
from .auth import IsRunner, RunnerTokenAuthentication
from .serializers import (
    AlertInboundSerializer,
    FinishRunSerializer,
    PhotoUploadSerializer,
    RunUrlSerializer,
    ScrapedListingSerializer,
    ScrapedPhotoSerializer,
    StartRunSerializer,
)


class AlertInboundView(APIView):
    """Inbound-email webhook: platform saved-search alerts are forwarded here."""

    authentication_classes = []
    permission_classes = [AllowAny]  # guarded by the shared secret below
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    throttle_scope = "alerts_inbound"

    def post(self, request):
        expected = settings.ALERT_INBOUND_TOKEN
        given = request.headers.get("X-Alert-Token") or request.query_params.get("token", "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        serializer = AlertInboundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            alert = ingest_alert(**serializer.validated_data)
        except UnknownPlatform as e:
            # 200 so the mail provider does not retry something that can never be accepted
            return Response({"ignored": str(e)})
        return Response({"alert_id": alert.id, "platform": alert.platform, "listings": alert.parsed_count},
                        status=status.HTTP_201_CREATED)


class RunnerView(APIView):
    authentication_classes = [RunnerTokenAuthentication]
    permission_classes = [IsRunner]
    throttle_scope = "sync"

    def handle_exception(self, exc):
        if isinstance(exc, runs.RunStateError):
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        if isinstance(exc, runs.NotAllowlisted):
            return Response({"detail": "That URL is not on this run's allowlist."},
                            status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, (IngestError, InvalidPhoto)):
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return super().handle_exception(exc)


class PlatformsView(RunnerView):
    """Which platforms are switched on, and their daily slot (UK time)."""

    def get(self, request):
        return Response({p: {"enabled": runs.sync_enabled(p), "slot": get_setting(f"sync_slot_{p}")}
                         for p in PLATFORMS})


class ScrapeSettingsView(RunnerView):
    """The filters the scrape command uses unless it is given others."""

    def get(self, request):
        return Response({"max_mileage": get_setting("scrape_max_mileage"),
                         "min_year": get_setting("scrape_min_year")})


class NextRunView(RunnerView):
    """Today's run for a platform, prepared now if its slot has passed; otherwise the reason there is none."""

    def get(self, request):
        platform = request.query_params.get("platform")
        if platform not in PLATFORMS:
            return Response({"detail": "Give a known platform."}, status=status.HTTP_400_BAD_REQUEST)
        expire_listings()  # keep statuses right even when no worker is running
        run, reason = runs.run_for_runner(platform)
        if run is None:
            return Response({"run": None, "reason": reason})
        return Response({"run": {"id": run.id, "platform": run.platform, "uk_date": run.uk_date,
                                 "urls": run.allowlist, "delay_ms": settings.SYNC_DELAY_MS}, "reason": ""})


class StartRunView(RunnerView):
    def post(self, request, run_id):
        serializer = StartRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        get_object_or_404(SyncRun, pk=run_id)
        run = runs.start_run(run_id, serializer.validated_data["session_ok"])
        return Response({"id": run.id, "status": run.status, "stop_reason": run.stop_reason})


class RunUrlView(RunnerView):
    """One call per URL opened: its outcome and, when captured, the scraped record."""

    def post(self, request, run_id):
        serializer = RunUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = get_object_or_404(SyncRun, pk=run_id)
        listing = runs.record_url(run, **serializer.validated_data)
        if listing is None:
            return Response({"logged": True})
        return Response({"logged": True, "listing_id": listing.id, "missing_photos": missing_positions(listing)})


class RunPhotoView(RunnerView):
    parser_classes = [MultiPartParser]

    def post(self, request, run_id):
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = get_object_or_404(SyncRun, pk=run_id)
        if run.status != SyncRun.Status.RUNNING:
            raise runs.RunStateError(f"Run is {run.status}; it is not accepting photos.")
        if data["url"] not in run.allowlist:
            raise runs.NotAllowlisted(data["url"])
        external_id, _ = PLATFORMS[run.platform].match(data["url"])
        listing = get_object_or_404(Listing, platform=run.platform, external_id=external_id)
        photo = get_object_or_404(listing.photos, position=data["position"])
        store_photo(photo, data["file"])
        make_thumbnail.delay(str(photo.id))
        return Response({"stored": True, "position": photo.position}, status=status.HTTP_201_CREATED)


class ScrapedListingView(RunnerView):
    """A car the scrape command found on a platform's search: saved (or updated) as a listing."""

    def post(self, request):
        serializer = ScrapedListingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing, created = save_scraped(**serializer.validated_data)
        return Response({"listing_id": listing.id, "created": created, "external_id": listing.external_id,
                         "missing_photos": missing_positions(listing)})


class ScrapedPhotoView(RunnerView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = ScrapedPhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        listing = get_object_or_404(Listing, platform=data["platform"], external_id=data["external_id"])
        photo = get_object_or_404(listing.photos, position=data["position"])
        store_photo(photo, data["file"])
        make_thumbnail.delay(str(photo.id))
        return Response({"stored": True, "position": photo.position}, status=status.HTTP_201_CREATED)


class FinishRunView(RunnerView):
    def post(self, request, run_id):
        serializer = FinishRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = get_object_or_404(SyncRun, pk=run_id)
        run = runs.finish_run(run, serializer.validated_data["status"],
                              serializer.validated_data.get("stop_reason", ""))
        return Response({"id": run.id, "status": run.status, "listings_captured": run.listings_captured})
