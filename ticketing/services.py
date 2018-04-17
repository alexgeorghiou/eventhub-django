"""Ticket purchasing and cancellation.

The interesting part is concurrency. Two buyers racing for the last seat must
not both succeed, so every write that changes ``TicketTier.quantity_sold`` or
``PromoCode.times_used`` happens inside one transaction that first takes a row
lock with ``select_for_update()``. On PostgreSQL the second buyer blocks until
the first commits and then re-reads the updated counter. SQLite has no row
locks but serialises writers on the whole database, which gives the same
outcome for local development and tests.

Rows are always locked in the same order (tier, then promo code) to avoid
deadlocks between concurrent purchases.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .exceptions import (
    InsufficientCapacity,
    InvalidPromoCode,
    InvalidQuantity,
    OrderNotCancellable,
    SalesClosed,
)
from .models import ZERO, Order, PromoCode, Ticket, TicketTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Attendee:
    name: str
    email: str


@dataclass(frozen=True)
class Quote:
    quantity: int
    unit_price: Decimal
    discount_per_ticket: Decimal
    currency: str

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def discount_total(self) -> Decimal:
        return self.discount_per_ticket * self.quantity

    @property
    def total(self) -> Decimal:
        return max(self.subtotal - self.discount_total, ZERO)


def max_tickets_per_order() -> int:
    return settings.EVENTHUB["MAX_TICKETS_PER_ORDER"]


def validate_promo(promo: PromoCode, tier: TicketTier, at=None) -> None:
    """Raise :class:`InvalidPromoCode` unless ``promo`` can be applied to ``tier``."""
    at = at or timezone.now()
    if not promo.is_active or promo.event_id != tier.event_id:
        raise InvalidPromoCode("This promo code is not valid for this event.")
    if promo.valid_from and at < promo.valid_from:
        raise InvalidPromoCode("This promo code is not active yet.")
    if promo.valid_until and at > promo.valid_until:
        raise InvalidPromoCode("This promo code has expired.")
    if promo.max_uses is not None and promo.times_used >= promo.max_uses:
        raise InvalidPromoCode("This promo code has been fully redeemed.")
    restricted_to = list(promo.tiers.values_list("pk", flat=True))
    if restricted_to and tier.pk not in restricted_to:
        raise InvalidPromoCode("This promo code does not apply to the selected ticket.")


def find_promo(event_id: int, code: str, *, lock: bool = False) -> PromoCode:
    qs = PromoCode.objects.select_for_update() if lock else PromoCode.objects.all()
    try:
        return qs.get(event_id=event_id, code=code.strip().upper())
    except PromoCode.DoesNotExist:
        raise InvalidPromoCode("Unknown promo code.") from None


def quote(tier: TicketTier, quantity: int, promo: PromoCode | None = None) -> Quote:
    """Price an order without reserving anything."""
    _check_quantity(quantity)
    discount = ZERO
    if promo is not None:
        validate_promo(promo, tier)
        discount = promo.discount_per_ticket(tier.price)
    return Quote(
        quantity=quantity,
        unit_price=tier.price,
        discount_per_ticket=discount,
        currency=tier.currency,
    )


def _check_quantity(quantity: int) -> None:
    limit = max_tickets_per_order()
    if quantity < 1 or quantity > limit:
        raise InvalidQuantity(f"You can buy between 1 and {limit} tickets per order.")


@transaction.atomic
def purchase_tickets(
    *,
    tier_id: int,
    quantity: int,
    buyer_name: str,
    buyer_email: str,
    promo_code: str = "",
    attendees: Sequence[Attendee] | None = None,
    user=None,
) -> Order:
    """Atomically reserve ``quantity`` seats on a tier and issue tickets.

    ``attendees`` optionally names each ticket holder; missing entries default
    to the buyer.
    """
    _check_quantity(quantity)
    if attendees and len(attendees) > quantity:
        raise InvalidQuantity("More attendees were supplied than tickets requested.")

    # Lock the tier row first. Any concurrent purchase on the same tier waits
    # here until we commit or roll back.
    tier = TicketTier.objects.select_for_update().select_related("event").get(pk=tier_id)
    if not tier.is_on_sale():
        raise SalesClosed("Tickets for this tier are not on sale.")
    if tier.remaining < quantity:
        if tier.remaining == 0:
            raise InsufficientCapacity(f"'{tier.name}' is sold out.")
        raise InsufficientCapacity(f"Only {tier.remaining} '{tier.name}' tickets left.")

    promo = None
    if promo_code.strip():
        promo = find_promo(tier.event_id, promo_code, lock=True)
    priced = quote(tier, quantity, promo)

    TicketTier.objects.filter(pk=tier.pk).update(quantity_sold=F("quantity_sold") + quantity)
    if promo is not None:
        PromoCode.objects.filter(pk=promo.pk).update(times_used=F("times_used") + 1)

    order = Order.objects.create(
        event=tier.event,
        tier=tier,
        promo_code=promo,
        user=user if getattr(user, "is_authenticated", False) else None,
        buyer_name=buyer_name.strip(),
        buyer_email=buyer_email.strip().lower(),
        quantity=quantity,
        unit_price=priced.unit_price,
        discount_total=priced.discount_total,
        total=priced.total,
        currency=priced.currency,
    )
    holders = list(attendees or [])
    holders += [Attendee(order.buyer_name, order.buyer_email)] * (quantity - len(holders))
    Ticket.objects.bulk_create(
        Ticket(
            order=order,
            tier=tier,
            attendee_name=a.name.strip() or order.buyer_name,
            attendee_email=(a.email.strip() or order.buyer_email).lower(),
        )
        for a in holders
    )
    logger.info("order %s: %d x %s for %s", order.reference, quantity, tier, order.buyer_email)

    from .tasks import send_order_confirmation

    order_id = order.pk
    transaction.on_commit(lambda: send_order_confirmation.delay(order_id))
    return order


@transaction.atomic
def cancel_order(order: Order) -> Order:
    """Cancel an order and release its seats back to the tier."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status == Order.Status.CANCELLED:
        raise OrderNotCancellable("Order is already cancelled.")
    if order.tickets.checked_in().exists():
        raise OrderNotCancellable("Tickets in this order have already been used.")

    # Same lock order as purchase_tickets: tier first, then promo code.
    TicketTier.objects.select_for_update().filter(pk=order.tier_id).update(
        quantity_sold=F("quantity_sold") - order.quantity
    )
    if order.promo_code_id:
        PromoCode.objects.select_for_update().filter(pk=order.promo_code_id).update(
            times_used=F("times_used") - 1
        )
    order.tickets.update(status=Ticket.Status.CANCELLED)
    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=["status", "cancelled_at"])
    logger.info("order %s cancelled", order.reference)
    return order
