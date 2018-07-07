"""Transactional emails. Rendering lives here; Celery tasks only orchestrate."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from checkin.tokens import make_order_token

from .models import Order, Ticket


def order_url(order: Order) -> str:
    path = reverse("ticketing:order", kwargs={"token": make_order_token(order)})
    return settings.EVENTHUB["SITE_URL"].rstrip("/") + path


def _send(subject: str, to: str, template: str, context: dict) -> None:
    text = render_to_string(f"emails/{template}.txt", context)
    html = render_to_string(f"emails/{template}.html", context)
    message = EmailMultiAlternatives(subject.strip(), text, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html, "text/html")
    message.send()


def send_confirmation_email(order: Order) -> None:
    context = {
        "order": order,
        "event": order.event,
        "tickets": list(order.tickets.all()),
        "order_url": order_url(order),
    }
    _send(
        f"Your tickets for {order.event.title} ({order.reference})",
        order.buyer_email,
        "order_confirmation",
        context,
    )


def send_reminder_email(ticket: Ticket) -> None:
    event = ticket.tier.event
    context = {"ticket": ticket, "event": event, "order_url": order_url(ticket.order)}
    _send(f"Reminder: {event.title} starts soon", ticket.attendee_email, "event_reminder", context)
