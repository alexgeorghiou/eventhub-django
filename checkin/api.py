from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from events.models import Event
from ticketing.models import Ticket

from .services import check_in


class ScanSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)


class CheckInView(APIView):
    """POST a scanned QR token to admit an attendee. Staff only."""

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, slug: str):
        event = get_object_or_404(Event, slug=slug)
        payload = ScanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        outcome = check_in(payload.validated_data["token"], event, scanned_by=request.user)
        body = {
            "result": outcome.result.value,
            "admitted": outcome.admitted,
            "message": outcome.result.label,
        }
        if outcome.ticket is not None:
            t = outcome.ticket
            body["ticket"] = {
                "short_code": t.short_code,
                "attendee_name": t.attendee_name,
                "tier": t.tier.name,
                "checked_in_at": t.checked_in_at,
            }
        return Response(body)


class EventStatsView(APIView):
    """Live attendance numbers for the door team."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, slug: str):
        event = get_object_or_404(Event, slug=slug)
        valid = Q(tickets__status=Ticket.Status.VALID)
        tiers = event.tiers.annotate(
            issued=Count("tickets", filter=valid),
            checked_in=Count("tickets", filter=valid & Q(tickets__checked_in_at__isnull=False)),
        )
        rows = [
            {"tier": t.name, "capacity": t.capacity, "sold": t.issued, "checked_in": t.checked_in}
            for t in tiers
        ]
        return Response(
            {
                "event": event.slug,
                "sold": sum(r["sold"] for r in rows),
                "checked_in": sum(r["checked_in"] for r in rows),
                "capacity": sum(r["capacity"] for r in rows),
                "tiers": rows,
            }
        )
