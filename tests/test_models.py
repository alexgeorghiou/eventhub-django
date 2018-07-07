from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from events.models import Event, Session, Track
from ticketing.models import PromoCode, TicketTier

pytestmark = pytest.mark.django_db


def test_event_slug_is_generated_and_unique(make_event):
    first = make_event(title="Python Summit")
    second = make_event(title="Python Summit")
    assert first.slug == "python-summit"
    assert second.slug == "python-summit-2"


def test_event_must_end_after_start(make_event):
    now = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(starts_at=now, ends_at=now - timedelta(hours=1))


def test_published_upcoming_queryset(make_event):
    past_start = timezone.now() - timedelta(days=5)
    make_event(title="Past", starts_at=past_start, ends_at=past_start + timedelta(days=1))
    make_event(title="Draft", is_published=False)
    live = make_event(title="Live")
    assert list(Event.objects.published().upcoming()) == [live]


def test_session_must_fit_inside_event(event):
    session = Session(
        event=event,
        title="Too early",
        starts_at=event.starts_at - timedelta(hours=2),
        ends_at=event.starts_at - timedelta(hours=1),
    )
    with pytest.raises(ValidationError) as exc:
        session.full_clean()
    assert "starts_at" in exc.value.message_dict


def test_session_track_must_belong_to_event(event, make_event):
    other_track = Track.objects.create(event=make_event(title="Other"), name="Elsewhere")
    session = Session(
        event=event,
        track=other_track,
        title="Mismatch",
        starts_at=event.starts_at,
        ends_at=event.starts_at + timedelta(hours=1),
    )
    with pytest.raises(ValidationError) as exc:
        session.full_clean()
    assert "track" in exc.value.message_dict


def test_room_double_booking_is_rejected(programme):
    existing = programme["session"]
    clash = Session(
        event=existing.event,
        title="Clash",
        room="room 1",
        starts_at=existing.starts_at + timedelta(minutes=30),
        ends_at=existing.ends_at + timedelta(minutes=30),
    )
    with pytest.raises(ValidationError) as exc:
        clash.full_clean()
    assert "room" in exc.value.message_dict


def test_session_duration(programme):
    assert programme["session"].duration_minutes == 60


def test_tier_capacity_is_enforced_by_database(tier):
    with pytest.raises(IntegrityError), transaction.atomic():
        TicketTier.objects.filter(pk=tier.pk).update(quantity_sold=tier.capacity + 1)


def test_tier_sales_window(make_tier):
    now = timezone.now()
    future = make_tier(name="Later", sales_start=now + timedelta(days=1))
    closed = make_tier(name="Closed", sales_end=now - timedelta(minutes=1))
    open_ = make_tier(name="Open", sales_start=now - timedelta(days=1))
    inactive = make_tier(name="Inactive", is_active=False)
    assert not future.is_on_sale()
    assert not closed.is_on_sale()
    assert open_.is_on_sale()
    assert not inactive.is_on_sale()


@pytest.mark.parametrize(
    ("kind", "amount", "price", "expected"),
    [
        ("percent", "25", "100.00", "25.00"),
        ("percent", "33", "9.99", "3.30"),
        ("fixed", "15", "100.00", "15"),
        ("fixed", "150", "100.00", "100.00"),  # never discounts below zero
    ],
)
def test_promo_discount_per_ticket(event, kind, amount, price, expected):
    promo = PromoCode(event=event, code="X", discount_type=kind, amount=Decimal(amount))
    assert promo.discount_per_ticket(Decimal(price)) == Decimal(expected)


def test_promo_code_is_normalised(promo):
    assert promo.code == "SAVE25"


def test_percentage_promo_cannot_exceed_100(event):
    with pytest.raises(IntegrityError), transaction.atomic():
        PromoCode.objects.create(event=event, code="FREE", amount=Decimal("120"))
