from __future__ import annotations

import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from events.models import Event

ZERO = Decimal("0.00")


class TicketTier(models.Model):
    """A purchasable ticket type with a fixed capacity, e.g. "Early bird"."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tiers")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(ZERO)]
    )
    currency = models.CharField(max_length=3, default="EUR")
    capacity = models.PositiveIntegerField()
    # Denormalised counter, only ever changed while the row is locked with
    # SELECT ... FOR UPDATE. The check constraint below is the last line of
    # defence against overselling should application code ever get it wrong.
    quantity_sold = models.PositiveIntegerField(default=0, editable=False)
    sales_start = models.DateTimeField(null=True, blank=True)
    sales_end = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["event", "position", "price"]
        constraints = [
            models.CheckConstraint(
                check=Q(quantity_sold__lte=F("capacity")), name="tier_not_oversold"
            ),
            models.UniqueConstraint(fields=["event", "name"], name="unique_tier_name_per_event"),
        ]

    def __str__(self) -> str:
        return f"{self.event} - {self.name}"

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.quantity_sold, 0)

    @property
    def is_sold_out(self) -> bool:
        return self.remaining == 0

    def is_on_sale(self, at=None) -> bool:
        at = at or timezone.now()
        if not self.is_active or self.event.has_ended:
            return False
        if self.sales_start and at < self.sales_start:
            return False
        return not (self.sales_end and at > self.sales_end)


class PromoCode(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage"
        FIXED = "fixed", "Fixed amount per ticket"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="promo_codes")
    code = models.CharField(max_length=40)
    discount_type = models.CharField(
        max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    amount = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(ZERO)]
    )
    max_uses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of orders that may use this code; blank = unlimited",
    )
    times_used = models.PositiveIntegerField(default=0, editable=False)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    tiers = models.ManyToManyField(
        TicketTier, blank=True, help_text="Restrict to these tiers; leave empty for all tiers"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["event", "code"]
        constraints = [
            models.UniqueConstraint(fields=["event", "code"], name="unique_promo_per_event"),
            models.CheckConstraint(
                check=Q(max_uses__isnull=True) | Q(times_used__lte=F("max_uses")),
                name="promo_not_overused",
            ),
            models.CheckConstraint(
                check=~Q(discount_type="percent") | Q(amount__lte=100),
                name="promo_percent_max_100",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs) -> None:
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @property
    def uses_remaining(self) -> int | None:
        if self.max_uses is None:
            return None
        return max(self.max_uses - self.times_used, 0)

    def discount_per_ticket(self, unit_price: Decimal) -> Decimal:
        if self.discount_type == self.DiscountType.PERCENT:
            discount = (unit_price * self.amount / Decimal(100)).quantize(Decimal("0.01"))
        else:
            discount = self.amount
        return min(discount, unit_price)


def _order_reference() -> str:
    # Short, human friendly, no ambiguous characters.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "EH-" + "".join(secrets.choice(alphabet) for _ in range(8))


class Order(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=16, unique=True, default=_order_reference)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="orders")
    tier = models.ForeignKey(TicketTier, on_delete=models.PROTECT, related_name="orders")
    promo_code = models.ForeignKey(
        PromoCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_orders",
    )
    buyer_name = models.CharField(max_length=150)
    buyer_email = models.EmailField()
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    discount_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    confirmation_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["buyer_email"])]

    def __str__(self) -> str:
        return self.reference


class TicketQuerySet(models.QuerySet["Ticket"]):
    def valid(self) -> TicketQuerySet:
        return self.filter(status=Ticket.Status.VALID)

    def checked_in(self) -> TicketQuerySet:
        return self.filter(checked_in_at__isnull=False)


class Ticket(models.Model):
    class Status(models.TextChoices):
        VALID = "valid", "Valid"
        CANCELLED = "cancelled", "Cancelled"

    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="tickets")
    tier = models.ForeignKey(TicketTier, on_delete=models.PROTECT, related_name="tickets")
    attendee_name = models.CharField(max_length=150)
    attendee_email = models.EmailField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VALID)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    objects = TicketQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.attendee_name} ({self.short_code})"

    @property
    def short_code(self) -> str:
        return self.code.hex[:8].upper()

    @property
    def event(self) -> Event:
        return self.tier.event

    @property
    def is_checked_in(self) -> bool:
        return self.checked_in_at is not None
