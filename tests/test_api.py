from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from checkin.tokens import make_ticket_token
from ticketing.models import Order

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_throttles():
    cache.clear()


def _order_payload(tier, **overrides):
    data = {"tier": tier.pk, "quantity": 2, "buyer_name": "Linus", "buyer_email": "l@example.com"}
    data.update(overrides)
    return data


def test_event_list_hides_drafts_and_past(api_client, make_event):
    make_event(title="Visible")
    make_event(title="Draft", is_published=False)
    past = timezone.now() - timedelta(days=3)
    make_event(title="Past", starts_at=past, ends_at=past + timedelta(days=1))
    response = api_client.get("/api/events/")
    assert response.status_code == 200
    assert [e["title"] for e in response.json()["results"]] == ["Visible"]


def test_event_detail_includes_tiers_with_remaining(api_client, event, tier, buy):
    buy(2)
    body = api_client.get(f"/api/events/{event.slug}/").json()
    assert body["tiers"][0]["remaining"] == 3
    assert body["tiers"][0]["on_sale"] is True


def test_draft_event_detail_is_404_for_public(api_client, make_event):
    draft = make_event(title="Secret", is_published=False)
    assert api_client.get(f"/api/events/{draft.slug}/").status_code == 404


def test_sessions_and_speakers_endpoints(api_client, event, programme):
    sessions = api_client.get(f"/api/events/{event.slug}/sessions/").json()
    assert sessions[0]["title"] == "Engines of computation"
    assert sessions[0]["speakers"][0]["name"] == "Ada Lovelace"
    assert sessions[0]["track"]["name"] == "Backend"
    speakers = api_client.get(f"/api/events/{event.slug}/speakers/").json()
    assert [s["name"] for s in speakers] == ["Ada Lovelace"]


def test_anonymous_purchase(api_client, tier, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post("/api/orders/", _order_payload(tier), format="json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["quantity"] == 2
    assert body["total"] == "200.00"
    assert len(body["tickets"]) == 2
    assert body["tickets"][0]["qr_token"]
    assert "/orders/" in body["tickets_url"]


def test_purchase_sold_out_returns_409(api_client, tier, buy):
    buy(5)
    response = api_client.post("/api/orders/", _order_payload(tier, quantity=1), format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "insufficient_capacity"


def test_purchase_with_bad_promo_returns_400(api_client, tier):
    response = api_client.post("/api/orders/", _order_payload(tier, promo_code="BOGUS"),
                               format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_promo_code"


def test_purchase_validation_errors(api_client, tier):
    response = api_client.post("/api/orders/", _order_payload(tier, quantity=50,
                                                               buyer_email="nope"), format="json")
    assert response.status_code == 400
    assert set(response.json()) == {"quantity", "buyer_email"}


def test_quote(api_client, tier, promo):
    response = api_client.post("/api/quote/", {"tier": tier.pk, "quantity": 2,
                                               "promo_code": "save25"}, format="json")
    assert response.status_code == 200
    assert response.json()["total"] == "150.00"
    assert response.json()["remaining"] == 5


def test_orders_list_requires_auth_and_scopes_to_user(api_client, django_user_model, tier, buy):
    assert api_client.get("/api/orders/").status_code == 403
    user = django_user_model.objects.create_user("buyer", password="pw-buyer-123")
    buy(1, user=user)
    buy(1, buyer_email="someone@example.com")
    api_client.force_authenticate(user)
    results = api_client.get("/api/orders/").json()["results"]
    assert len(results) == 1


def test_staff_can_cancel_order(staff_api, buy, tier):
    order = buy(2)
    response = staff_api.post(f"/api/orders/{order.reference}/cancel/")
    assert response.status_code == 200
    assert response.json()["status"] == Order.Status.CANCELLED
    tier.refresh_from_db()
    assert tier.quantity_sold == 0
    again = staff_api.post(f"/api/orders/{order.reference}/cancel/")
    assert again.status_code == 400


def test_checkin_endpoint(staff_api, buy, event):
    ticket = buy(1).tickets.get()
    url = f"/api/events/{event.slug}/checkin/"
    first = staff_api.post(url, {"token": make_ticket_token(ticket)}, format="json").json()
    assert first["admitted"] is True
    assert first["ticket"]["attendee_name"] == "Grace Hopper"
    second = staff_api.post(url, {"token": make_ticket_token(ticket)}, format="json").json()
    assert second["result"] == "already_checked_in"


def test_checkin_requires_staff(api_client, event):
    response = api_client.post(f"/api/events/{event.slug}/checkin/", {"token": "x"})
    assert response.status_code == 403


def test_event_stats(staff_api, buy, event, make_tier):
    vip = make_tier(name="VIP", capacity=2)
    order = buy(3)
    buy(1, target=vip)
    staff_api.post(f"/api/events/{event.slug}/checkin/",
                   {"token": make_ticket_token(order.tickets.first())}, format="json")
    stats = staff_api.get(f"/api/events/{event.slug}/stats/").json()
    assert stats["sold"] == 4
    assert stats["checked_in"] == 1
    assert stats["capacity"] == 7
    assert {t["tier"]: t["sold"] for t in stats["tiers"]} == {"Standard": 3, "VIP": 1}
