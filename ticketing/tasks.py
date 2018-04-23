"""Celery tasks: order confirmations and scheduled event reminders."""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .emails import send_confirmation_email, send_reminder_email
from .models import Order, Ticket

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=5)
def send_order_confirmation(self, order_id: int) -> bool:
    order = Order.objects.select_related("event", "tier").filter(pk=order_id).first()
    if order is None or order.confirmation_sent_at is not None:
        return False
    send_confirmation_email(order)
    Order.objects.filter(pk=order.pk).update(confirmation_sent_at=timezone.now())
    return True


@shared_task
def send_event_reminders() -> int:
    """Email every valid ticket holder whose event starts within the lead time.

    Runs periodically from Celery beat. Each ticket is claimed with
    ``select_for_update(skip_locked=True)`` so overlapping runs (or several
    beat-triggered workers) never send the same reminder twice.
    """
    now = timezone.now()
    horizon = now + settings.EVENTHUB["REMINDER_LEAD_TIME"]
    due = Ticket.objects.valid().filter(
        reminder_sent_at__isnull=True,
        tier__event__starts_at__gt=now,
        tier__event__starts_at__lte=horizon,
    )
    sent = 0
    for ticket_id in due.values_list("pk", flat=True).iterator():
        sent += _remind(ticket_id)
    if sent:
        logger.info("sent %d event reminders", sent)
    return sent


def _remind(ticket_id: int) -> int:
    with transaction.atomic():
        ticket = (
            Ticket.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("tier__event", "order")
            .filter(pk=ticket_id, reminder_sent_at__isnull=True)
            .first()
        )
        if ticket is None:
            return 0
        send_reminder_email(ticket)
        ticket.reminder_sent_at = timezone.now()
        ticket.save(update_fields=["reminder_sent_at"])
        return 1


@shared_task
def send_reminders_for_event(event_id: int) -> int:
    """Manually triggered from the admin; ignores the lead-time window."""
    sent = 0
    tickets = Ticket.objects.valid().filter(tier__event_id=event_id, reminder_sent_at__isnull=True)
    for ticket_id in tickets.values_list("pk", flat=True):
        sent += _remind(ticket_id)
    return sent
