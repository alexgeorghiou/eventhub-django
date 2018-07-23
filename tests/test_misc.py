import pytest
from django.core.management import call_command

from config.env import env_bool, env_int, env_list
from events.models import Event
from ticketing.services import purchase_tickets


@pytest.mark.django_db
def test_seed_demo_is_idempotent_and_sellable():
    call_command("seed_demo")
    call_command("seed_demo")
    event = Event.objects.get(slug="pycon-riverside")
    assert event.sessions.count() == 8
    assert event.tiers.count() == 3
    early = event.tiers.get(name="Early bird")
    order = purchase_tickets(
        tier_id=early.pk,
        quantity=1,
        buyer_name="Demo",
        buyer_email="demo@example.com",
        promo_code="community20",
    )
    assert str(order.total) == "63.20"


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("X_BOOL", "Yes")
    monkeypatch.setenv("X_INT", "42")
    monkeypatch.setenv("X_LIST", "a, b,,c ")
    assert env_bool("X_BOOL") is True
    assert env_bool("X_MISSING", default=True) is True
    assert env_int("X_INT", default=1) == 42
    assert env_int("X_MISSING", default=7) == 7
    assert env_list("X_LIST", default=[]) == ["a", "b", "c"]
    assert env_list("X_MISSING", default=["z"]) == ["z"]
