"""Door check-in.

Scanning is idempotent from the attendee's point of view: the first scan admits,
every later scan reports "already checked in" together with when it happened.
The ticket row is locked while we decide so two scanners at different doors
cannot both admit the same ticket.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from events.models import Event
from ticketing.models import Ticket

from .models import ScanLog, ScanResult
from .tokens import InvalidToken, read_ticket_token


@dataclass(frozen=True)
class CheckInOutcome:
    result: ScanResult
    ticket: Ticket | None = None

    @property
    def admitted(self) -> bool:
        return self.result == ScanResult.ADMITTED


@transaction.atomic
def check_in(token: str, event: Event, scanned_by=None) -> CheckInOutcome:
    outcome = _evaluate(token, event, scanned_by)
    ScanLog.objects.create(
        event=event, ticket=outcome.ticket, result=outcome.result, scanned_by=scanned_by
    )
    return outcome


def _evaluate(token: str, event: Event, scanned_by) -> CheckInOutcome:
    try:
        claim = read_ticket_token(token)
    except InvalidToken:
        return CheckInOutcome(ScanResult.INVALID)

    if claim.event_id != event.pk:
        return CheckInOutcome(ScanResult.WRONG_EVENT)

    ticket = (
        Ticket.objects.select_for_update()
        .select_related("tier", "order")
        .filter(code=claim.ticket_code, tier__event=event)
        .first()
    )
    if ticket is None:
        return CheckInOutcome(ScanResult.INVALID)
    if ticket.status == Ticket.Status.CANCELLED:
        return CheckInOutcome(ScanResult.CANCELLED, ticket)
    if ticket.is_checked_in:
        return CheckInOutcome(ScanResult.ALREADY_CHECKED_IN, ticket)

    ticket.checked_in_at = timezone.now()
    ticket.checked_in_by = scanned_by if getattr(scanned_by, "is_authenticated", False) else None
    ticket.save(update_fields=["checked_in_at", "checked_in_by"])
    return CheckInOutcome(ScanResult.ADMITTED, ticket)
