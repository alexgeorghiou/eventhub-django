import pytest
from django.urls import reverse

from ticketing.models import Order, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client_(client, staff_user):
    client.force_login(staff_user)
    return client


@pytest.mark.parametrize(
    "model",
    ["events_event", "events_session", "events_speaker", "ticketing_order", "ticketing_ticket",
     "ticketing_tickettier", "ticketing_promocode", "checkin_scanlog"],
)
def test_changelists_render(admin_client_, buy, programme, model):
    buy(1)
    assert admin_client_.get(reverse(f"admin:{model}_changelist")).status_code == 200


def test_event_changelist_shows_sales_progress(admin_client_, buy, event):
    buy(2)
    response = admin_client_.get(reverse("admin:events_event_changelist"))
    assert b"2 / 5" in response.content
    assert b"Open scanner" in response.content


def test_event_change_form_renders_inlines(admin_client_, event, tier, promo):
    response = admin_client_.get(reverse("admin:events_event_change", args=[event.pk]))
    assert response.status_code == 200
    assert b"SAVE25" in response.content


def test_orders_cannot_be_added_in_admin(admin_client_):
    assert admin_client_.get(reverse("admin:ticketing_order_add")).status_code == 403


def test_cancel_orders_action(admin_client_, buy, tier):
    order = buy(2)
    admin_client_.post(reverse("admin:ticketing_order_changelist"),
                       {"action": "cancel_orders", "_selected_action": [order.pk]})
    order.refresh_from_db()
    tier.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert tier.quantity_sold == 0


def test_export_attendees_csv(admin_client_, buy):
    buy(2)
    ids = list(Ticket.objects.values_list("pk", flat=True))
    response = admin_client_.post(reverse("admin:ticketing_ticket_changelist"),
                                  {"action": "export_csv", "_selected_action": ids})
    assert response["Content-Type"] == "text/csv"
    lines = response.content.decode().strip().splitlines()
    assert lines[0].startswith("event,tier,ticket")
    assert len(lines) == 3


def test_publish_action(admin_client_, make_event):
    draft = make_event(title="Draft", is_published=False)
    admin_client_.post(reverse("admin:events_event_changelist"),
                       {"action": "publish", "_selected_action": [draft.pk]})
    draft.refresh_from_db()
    assert draft.is_published
