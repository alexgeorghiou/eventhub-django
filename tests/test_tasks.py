from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from ticketing.models import Ticket
from ticketing.services import cancel_order
from ticketing.tasks import send_event_reminders, send_order_confirmation, send_reminders_for_event

pytestmark = pytest.mark.django_db


def _move_event(event, starts_in: timedelta) -> None:
    event.starts_at = timezone.now() + starts_in
    event.ends_at = event.starts_at + timedelta(hours=8)
    event.save()


def test_confirmation_is_sent_once(buy):
    order = buy(1)
    mail.outbox.clear()
    assert send_order_confirmation(order.pk) is False
    assert mail.outbox == []


def test_confirmation_for_missing_order_is_noop():
    assert send_order_confirmation(999_999) is False


def test_confirmation_email_has_html_alternative(buy):
    buy(2)
    html, mime = mail.outbox[0].alternatives[0]
    assert mime == "text/html"
    assert "View your QR tickets" in html


def test_reminders_sent_within_lead_time(buy, event):
    buy(2, buyer_email="team@example.com")
    _move_event(event, timedelta(hours=6))
    mail.outbox.clear()

    assert send_event_reminders() == 2
    assert len(mail.outbox) == 2
    assert all("Reminder" in m.subject for m in mail.outbox)
    assert Ticket.objects.filter(reminder_sent_at__isnull=True).count() == 0


def test_reminders_are_not_repeated(buy, event):
    buy(1)
    _move_event(event, timedelta(hours=6))
    send_event_reminders()
    mail.outbox.clear()
    assert send_event_reminders() == 0
    assert mail.outbox == []


def test_no_reminders_for_events_far_away_or_past(buy, event):
    buy(1)
    _move_event(event, timedelta(days=3))
    assert send_event_reminders() == 0
    _move_event(event, -timedelta(hours=1))
    assert send_event_reminders() == 0


def test_cancelled_tickets_get_no_reminder(buy, event):
    order = buy(1)
    cancel_order(order)
    _move_event(event, timedelta(hours=2))
    assert send_event_reminders() == 0


def test_manual_reminders_ignore_lead_time(buy, event):
    buy(3)
    mail.outbox.clear()
    assert send_reminders_for_event(event.pk) == 3
    assert len(mail.outbox) == 3
