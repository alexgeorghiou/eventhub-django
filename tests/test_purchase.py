from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from ticketing.exceptions import (
    InsufficientCapacity,
    InvalidPromoCode,
    InvalidQuantity,
    OrderNotCancellable,
    SalesClosed,
)
from ticketing.models import Order, PromoCode, Ticket
from ticketing.services import Attendee, cancel_order, quote

pytestmark = pytest.mark.django_db


def test_purchase_issues_tickets_and_counts_capacity(buy, tier):
    order = buy(3)
    tier.refresh_from_db()
    assert order.status == Order.Status.CONFIRMED
    assert order.tickets.count() == 3
    assert tier.quantity_sold == 3
    assert tier.remaining == 2
    assert order.total == Decimal("300.00")
    assert order.reference.startswith("EH-")


def test_purchase_sends_confirmation_email(buy):
    order = buy(1)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert order.reference in message.subject
    assert message.to == ["grace@example.com"]
    assert "/orders/" in message.body
    order.refresh_from_db()
    assert order.confirmation_sent_at is not None


def test_cannot_buy_more_than_remaining(buy, tier):
    buy(4)
    with pytest.raises(InsufficientCapacity, match="Only 1"):
        buy(2)
    tier.refresh_from_db()
    assert tier.quantity_sold == 4


def test_sold_out_tier_rejects_purchase(buy):
    buy(5)
    with pytest.raises(InsufficientCapacity, match="sold out"):
        buy(1)
    assert Ticket.objects.count() == 5


def test_failed_purchase_leaves_no_partial_state(buy, tier):
    with pytest.raises(InvalidPromoCode):
        buy(2, promo_code="NOPE")
    tier.refresh_from_db()
    assert tier.quantity_sold == 0
    assert Order.objects.count() == 0


@pytest.mark.parametrize("quantity", [0, -1, 11])
def test_quantity_bounds(buy, quantity):
    with pytest.raises(InvalidQuantity):
        buy(quantity)


def test_sales_closed(buy, make_tier):
    closed = make_tier(name="Gone", sales_end=timezone.now() - timedelta(hours=1))
    with pytest.raises(SalesClosed):
        buy(1, target=closed)


def test_named_attendees(buy):
    order = buy(2, attendees=[Attendee("Alan Turing", "ALAN@example.com")])
    names = sorted(order.tickets.values_list("attendee_name", "attendee_email"))
    assert names == [("Alan Turing", "alan@example.com"), ("Grace Hopper", "grace@example.com")]


def test_more_attendees_than_tickets(buy):
    with pytest.raises(InvalidQuantity):
        buy(1, attendees=[Attendee("A", "a@example.com"), Attendee("B", "b@example.com")])


def test_percentage_promo_applied_case_insensitively(buy, promo):
    order = buy(2, promo_code=" save25 ")
    assert order.promo_code == promo
    assert order.discount_total == Decimal("50.00")
    assert order.total == Decimal("150.00")
    promo.refresh_from_db()
    assert promo.times_used == 1


def test_promo_usage_limit(buy, promo):
    buy(1, promo_code="SAVE25")
    buy(1, promo_code="SAVE25")
    with pytest.raises(InvalidPromoCode, match="fully redeemed"):
        buy(1, promo_code="SAVE25")


def test_promo_restricted_to_tiers(buy, promo, make_tier):
    vip = make_tier(name="VIP", price=Decimal("300.00"))
    promo.tiers.add(vip)
    with pytest.raises(InvalidPromoCode, match="does not apply"):
        buy(1, promo_code="SAVE25")
    assert buy(1, target=vip, promo_code="SAVE25").total == Decimal("225.00")


def test_promo_from_another_event_is_unknown(buy, make_event):
    PromoCode.objects.create(event=make_event(title="Other"), code="OTHER", amount=Decimal("10"))
    with pytest.raises(InvalidPromoCode, match="Unknown"):
        buy(1, promo_code="OTHER")


def test_expired_promo(buy, promo):
    promo.valid_until = timezone.now() - timedelta(minutes=1)
    promo.save()
    with pytest.raises(InvalidPromoCode, match="expired"):
        buy(1, promo_code="SAVE25")


def test_fixed_promo_on_free_tier_never_goes_negative(buy, event, make_tier):
    free = make_tier(name="Community", price=Decimal("0.00"))
    PromoCode.objects.create(event=event, code="TENOFF", discount_type="fixed",
                             amount=Decimal("10"))
    order = buy(1, target=free, promo_code="TENOFF")
    assert order.total == Decimal("0.00")


def test_quote_does_not_reserve(tier, promo):
    q = quote(tier, 3, promo)
    assert q.subtotal == Decimal("300.00")
    assert q.total == Decimal("225.00")
    tier.refresh_from_db()
    assert tier.quantity_sold == 0


def test_cancel_releases_capacity_and_promo_use(buy, tier, promo):
    order = buy(2, promo_code="SAVE25")
    cancel_order(order)
    tier.refresh_from_db()
    promo.refresh_from_db()
    order.refresh_from_db()
    assert tier.quantity_sold == 0
    assert promo.times_used == 0
    assert order.status == Order.Status.CANCELLED
    assert set(order.tickets.values_list("status", flat=True)) == {Ticket.Status.CANCELLED}
    # Seats are genuinely back on sale.
    assert buy(5).quantity == 5


def test_cannot_cancel_twice(buy):
    order = buy(1)
    cancel_order(order)
    with pytest.raises(OrderNotCancellable):
        cancel_order(order)


def test_cannot_cancel_after_check_in(buy):
    order = buy(1)
    order.tickets.update(checked_in_at=timezone.now())
    with pytest.raises(OrderNotCancellable):
        cancel_order(order)
