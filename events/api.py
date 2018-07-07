from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ticketing.models import TicketTier

from .models import Event, Session, Speaker, Track


class TrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Track
        fields = ["id", "name", "color"]


class SpeakerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Speaker
        fields = ["id", "slug", "name", "headline", "bio", "website", "photo_url"]


class SessionSerializer(serializers.ModelSerializer):
    track = TrackSerializer(read_only=True)
    speakers = SpeakerSerializer(many=True, read_only=True)

    class Meta:
        model = Session
        fields = [
            "id",
            "title",
            "abstract",
            "format",
            "level",
            "room",
            "starts_at",
            "ends_at",
            "duration_minutes",
            "track",
            "speakers",
        ]


class TierSerializer(serializers.ModelSerializer):
    remaining = serializers.IntegerField(read_only=True)
    on_sale = serializers.SerializerMethodField()

    class Meta:
        model = TicketTier
        fields = [
            "id",
            "name",
            "description",
            "price",
            "currency",
            "capacity",
            "remaining",
            "sales_start",
            "sales_end",
            "on_sale",
        ]

    def get_on_sale(self, tier: TicketTier) -> bool:
        return tier.is_on_sale() and not tier.is_sold_out


class EventListSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="api:event-detail", lookup_field="slug")

    class Meta:
        model = Event
        fields = ["url", "slug", "title", "tagline", "venue", "city", "starts_at", "ends_at"]


class EventDetailSerializer(EventListSerializer):
    tracks = TrackSerializer(many=True, read_only=True)
    tiers = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = [*EventListSerializer.Meta.fields, "description", "tracks", "tiers"]

    def get_tiers(self, event: Event):
        tiers = [t for t in event.tiers.all() if t.is_active]
        return TierSerializer(tiers, many=True, context=self.context).data


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    lookup_field = "slug"

    def get_queryset(self):
        qs = Event.objects.all()
        if not self.request.user.is_staff:
            qs = qs.published()
        if self.action == "list" and self.request.query_params.get("past") != "1":
            qs = qs.upcoming()
        return qs.prefetch_related("tracks", "tiers")

    def get_serializer_class(self):
        return EventListSerializer if self.action == "list" else EventDetailSerializer

    @action(detail=True)
    def sessions(self, request, slug=None):
        event = self.get_object()
        sessions = event.sessions.select_related("track").prefetch_related("speakers")
        track = request.query_params.get("track")
        if track:
            sessions = sessions.filter(track_id=track)
        return Response(SessionSerializer(sessions, many=True).data)

    @action(detail=True)
    def speakers(self, request, slug=None):
        event = self.get_object()
        speakers = Speaker.objects.filter(sessions__event=event).distinct()
        return Response(SpeakerSerializer(speakers, many=True).data)


class SpeakerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Speaker.objects.all()
    serializer_class = SpeakerSerializer
    lookup_field = "slug"
