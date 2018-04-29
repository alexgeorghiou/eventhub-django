from django.conf import settings
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from checkin.tokens import make_ticket_token

from . import services
from .emails import order_url
from .exceptions import InsufficientCapacity, TicketingError
from .models import Order, Ticket, TicketTier


class TicketingConflict(APIException):
    status_code = status.HTTP_409_CONFLICT


class TicketingBadRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST


def raise_api_error(exc: TicketingError):
    cls = TicketingConflict if isinstance(exc, InsufficientCapacity) else TicketingBadRequest
    raise cls(detail={"code": exc.code, "detail": exc.message}) from exc


class AttendeeSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()


class PurchaseSerializer(serializers.Serializer):
    tier = serializers.PrimaryKeyRelatedField(
        queryset=TicketTier.objects.filter(event__is_published=True)
    )
    quantity = serializers.IntegerField(min_value=1)
    buyer_name = serializers.CharField(max_length=150)
    buyer_email = serializers.EmailField()
    promo_code = serializers.CharField(max_length=40, required=False, allow_blank=True)
    attendees = AttendeeSerializer(many=True, required=False)

    def validate_quantity(self, value: int) -> int:
        limit = settings.EVENTHUB["MAX_TICKETS_PER_ORDER"]
        if value > limit:
            raise serializers.ValidationError(f"At most {limit} tickets per order.")
        return value


class QuoteSerializer(serializers.Serializer):
    tier = serializers.PrimaryKeyRelatedField(
        queryset=TicketTier.objects.filter(event__is_published=True)
    )
    quantity = serializers.IntegerField(min_value=1)
    promo_code = serializers.CharField(max_length=40, required=False, allow_blank=True)


class TicketSerializer(serializers.ModelSerializer):
    tier = serializers.CharField(source="tier.name")
    qr_token = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = ["code", "short_code", "tier", "attendee_name", "attendee_email", "status",
                  "checked_in_at", "qr_token"]

    def get_qr_token(self, ticket: Ticket) -> str:
        return make_ticket_token(ticket)


class OrderSerializer(serializers.ModelSerializer):
    event = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    tier = serializers.CharField(source="tier.name")
    promo_code = serializers.CharField(source="promo_code.code", default=None)
    tickets = TicketSerializer(many=True, read_only=True)
    tickets_url = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["reference", "event", "tier", "quantity", "unit_price", "discount_total",
                  "total", "currency", "promo_code", "buyer_name", "buyer_email", "status",
                  "created_at", "tickets", "tickets_url"]

    def get_tickets_url(self, order: Order) -> str:
        return order_url(order)


class PurchaseThrottle(AnonRateThrottle):
    scope = "purchase"
    rate = "20/minute"


class OrderViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """Create orders anonymously; list/retrieve your own (staff see all)."""

    lookup_field = "reference"
    serializer_class = OrderSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        if self.action == "cancel":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_throttles(self):
        return [PurchaseThrottle()] if self.action == "create" else super().get_throttles()

    def get_queryset(self):
        qs = Order.objects.select_related("event", "tier", "promo_code").prefetch_related(
            "tickets__tier"
        )
        user = self.request.user
        return qs if user.is_staff else qs.filter(user=user)

    def create(self, request, *args, **kwargs):
        payload = PurchaseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            order = services.purchase_tickets(
                tier_id=data["tier"].pk,
                quantity=data["quantity"],
                buyer_name=data["buyer_name"],
                buyer_email=data["buyer_email"],
                promo_code=data.get("promo_code", ""),
                attendees=[services.Attendee(**a) for a in data.get("attendees", [])],
                user=request.user,
            )
        except TicketingError as exc:
            raise_api_error(exc)
        order = Order.objects.prefetch_related("tickets__tier").get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        order = self.get_object()
        try:
            order = services.cancel_order(order)
        except TicketingError as exc:
            raise_api_error(exc)
        return Response(OrderSerializer(order).data)


class QuoteView(APIView):
    """Price a prospective order (and validate a promo code) without reserving seats."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        payload = QuoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tier = payload.validated_data["tier"]
        quantity = payload.validated_data["quantity"]
        code = payload.validated_data.get("promo_code", "").strip()
        try:
            promo = services.find_promo(tier.event_id, code) if code else None
            q = services.quote(tier, quantity, promo)
        except TicketingError as exc:
            raise_api_error(exc)
        return Response({
            "tier": tier.pk,
            "quantity": q.quantity,
            "unit_price": str(q.unit_price),
            "subtotal": str(q.subtotal),
            "discount_total": str(q.discount_total),
            "total": str(q.total),
            "currency": q.currency,
            "remaining": tier.remaining,
        })
