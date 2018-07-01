from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from config import celery_app
from events.models import Event, Session, Speaker, Track
from ticketing.models import PromoCode, TicketTier


@pytest.fixture(autouse=True)
def _eager_celery():
    # Tests never talk to a broker, even if CELERY_BROKER_URL leaks in from the env.
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def make_event(db):
    def factory(**overrides) -> Event:
        start = timezone.now() + timedelta(days=10)
        data = {
            "title": "DjangoCon Test",
            "venue": "Main Hall",
            "city": "Nicosia",
            "starts_at": start,
            "ends_at": start + timedelta(days=2),
            "is_published": True,
        }
        data.update(overrides)
        return Event.objects.create(**data)

    return factory


@pytest.fixture
def event(make_event) -> Event:
    return make_event()


@pytest.fixture
def make_tier(event):
    def factory(**overrides) -> TicketTier:
        data = {"event": event, "name": "Standard", "price": Decimal("100.00"), "capacity": 5}
        data.update(overrides)
        return TicketTier.objects.create(**data)

    return factory


@pytest.fixture
def tier(make_tier) -> TicketTier:
    return make_tier()


@pytest.fixture
def promo(event) -> PromoCode:
    return PromoCode.objects.create(event=event, code="save25", amount=Decimal("25"), max_uses=2)


@pytest.fixture
def programme(event):
    track = Track.objects.create(event=event, name="Backend")
    speaker = Speaker.objects.create(name="Ada Lovelace", headline="Analyst")
    session = Session.objects.create(
        event=event,
        track=track,
        title="Engines of computation",
        room="Room 1",
        starts_at=event.starts_at + timedelta(hours=1),
        ends_at=event.starts_at + timedelta(hours=2),
    )
    session.speakers.add(speaker)
    return {"track": track, "speaker": speaker, "session": session}


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        "door", "door@example.com", "pw-door-123", is_staff=True, is_superuser=True
    )


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_api(api_client, staff_user) -> APIClient:
    api_client.force_authenticate(staff_user)
    return api_client


@pytest.fixture
def buy(tier, django_capture_on_commit_callbacks):
    """Purchase helper that also runs on_commit hooks (i.e. the confirmation task)."""
    from ticketing.services import purchase_tickets

    def _buy(quantity: int = 1, target: TicketTier | None = None, **kwargs):
        kwargs.setdefault("buyer_name", "Grace Hopper")
        kwargs.setdefault("buyer_email", "grace@example.com")
        with django_capture_on_commit_callbacks(execute=True):
            return purchase_tickets(tier_id=(target or tier).pk, quantity=quantity, **kwargs)

    return _buy
