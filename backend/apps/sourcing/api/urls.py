from django.urls import path

from . import views

urlpatterns = [
    path("alerts/inbound", views.AlertInboundView.as_view(), name="alerts-inbound"),
    path("sync/platforms", views.PlatformsView.as_view(), name="sync-platforms"),
    path("scrape/settings", views.ScrapeSettingsView.as_view(), name="scrape-settings"),
    path("scrape/listings", views.ScrapedListingView.as_view(), name="scrape-listing"),
    path("scrape/photos", views.ScrapedPhotoView.as_view(), name="scrape-photo"),
    path("sync/next", views.NextRunView.as_view(), name="sync-next"),
    path("sync/runs/<uuid:run_id>/start", views.StartRunView.as_view(), name="sync-run-start"),
    path("sync/runs/<uuid:run_id>/urls", views.RunUrlView.as_view(), name="sync-run-url"),
    path("sync/runs/<uuid:run_id>/photos", views.RunPhotoView.as_view(), name="sync-run-photo"),
    path("sync/runs/<uuid:run_id>/report", views.FinishRunView.as_view(), name="sync-run-report"),
]
