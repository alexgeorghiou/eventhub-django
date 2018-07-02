import pytest
from django.core import mail
from django.urls import reverse

from checkin.models import ScanLog
from checkin.tokens import make_order_token, make_ticket_token
from ticketing.models import Order

pytestmark = pytest.mark.django_db


def test_home_lists_published_events(client, event, make_event):
    make_event(title="Hidden draft", is_published=False)
    response = client.get("/")
    assert response.status_code == 200
    assert event.title.encode() in response.content
    assert b"Hidden draft" not in response.content


def test_event_detail_shows_schedule_and_tiers(client, event, tier, programme):
    response = client.get(event.get_absolute_url())
    content = response.content.decode()
    assert response.status_code == 200
    assert "Engines of computation" in content
    assert "Ada Lovelace" in content
    assert tier.name in content


def test_speaker_page(client, programme):
    response = client.get(reverse("events:speaker", args=[programme["speaker"].slug]))
    assert response.status_code == 200
    assert b"Engines of computation" in response.content


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_register_flow(client, event, tier, django_capture_on_commit_callbacks):
    url = reverse("ticketing:register", args=[event.slug])
    assert client.get(url).status_code == 200
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(url, {"tier": tier.pk, "quantity": 2, "buyer_name": "Barbara",
                                     "buyer_email": "barbara@example.com"}, follow=True)
    assert response.status_code == 200
    order = Order.objects.get()
    assert order.quantity == 2
    assert b"Your tickets for" in response.content
    assert response.content.count(b"data:image/svg+xml") == 2
    assert len(mail.outbox) == 1


def test_register_shows_capacity_error(client, event, tier, buy):
    buy(5)
    response = client.post(reverse("ticketing:register", args=[event.slug]),
                           {"tier": tier.pk, "quantity": 1, "buyer_name": "Late",
                            "buyer_email": "late@example.com"})
    assert response.status_code == 200
    assert b"sold out" in response.content


def test_register_shows_promo_error_on_field(client, event, tier):
    response = client.post(reverse("ticketing:register", args=[event.slug]),
                           {"tier": tier.pk, "quantity": 1, "buyer_name": "X",
                            "buyer_email": "x@example.com", "promo_code": "NOPE"})
    assert response.context["form"].errors["promo_code"] == ["Unknown promo code."]


def test_order_page_requires_signed_token(client, buy):
    order = buy(1)
    assert client.get(f"/orders/{order.reference}/").status_code == 404
    ok = client.get(reverse("ticketing:order", args=[make_order_token(order)]))
    assert ok.status_code == 200


def test_ticket_qr_png(client, buy):
    ticket = buy(1).tickets.get()
    response = client.get(reverse("ticketing:ticket-qr", args=[make_ticket_token(ticket)]))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert client.get("/tickets/forged/qr.png").status_code == 404


def test_scanner_requires_staff(client, event):
    response = client.get(reverse("checkin:scanner", args=[event.slug]))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_scanner_form_post_checks_in(client, staff_user, buy, event):
    ticket = buy(1).tickets.get()
    client.force_login(staff_user)
    url = reverse("checkin:scanner", args=[event.slug])
    response = client.post(url, {"token": make_ticket_token(ticket)})
    assert response.status_code == 200
    assert response.context["outcome"].admitted
    assert ScanLog.objects.filter(event=event).count() == 1
