from django.urls import include, path
from rest_framework.routers import DefaultRouter

from checkin.api import CheckInView, EventStatsView
from events.api import EventViewSet, SpeakerViewSet
from ticketing.api import OrderViewSet, QuoteView

app_name = "api"

router = DefaultRouter()
router.register("events", EventViewSet, basename="event")
router.register("speakers", SpeakerViewSet, basename="speaker")
router.register("orders", OrderViewSet, basename="order")

urlpatterns = [
    path("quote/", QuoteView.as_view(), name="quote"),
    path("events/<slug:slug>/checkin/", CheckInView.as_view(), name="checkin"),
    path("events/<slug:slug>/stats/", EventStatsView.as_view(), name="event-stats"),
    path("", include(router.urls)),
]
