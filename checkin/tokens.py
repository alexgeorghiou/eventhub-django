"""Signed, tamper-proof tokens embedded in ticket QR codes.

A token is ``django.core.signing`` output over a tiny payload: the ticket's
UUID and its event id. Because it is HMAC-signed with ``SECRET_KEY`` a scanner
can reject forged or edited codes before touching the database, and the event
id lets a door scanner reject tickets for a different event outright.

Tokens deliberately carry no expiry of their own: validity is decided at scan
time against the ticket row (cancelled, already used, event over), which keeps
QR codes stable if an attendee printed theirs weeks ago.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.core import signing

SALT = "eventhub.checkin.ticket"
ORDER_SALT = "eventhub.order.access"


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class TicketClaim:
    ticket_code: uuid.UUID
    event_id: int


def make_ticket_token(ticket) -> str:
    payload = {"t": ticket.code.hex, "e": ticket.tier.event_id}
    return signing.dumps(payload, salt=SALT, compress=True)


def read_ticket_token(token: str) -> TicketClaim:
    try:
        payload = signing.loads(token.strip(), salt=SALT)
        return TicketClaim(ticket_code=uuid.UUID(hex=payload["t"]), event_id=int(payload["e"]))
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise InvalidToken("Ticket code is not valid.") from exc


def make_order_token(order) -> str:
    """Token used in the "view your tickets" link sent to buyers."""
    return signing.dumps(order.reference, salt=ORDER_SALT)


def read_order_token(token: str) -> str:
    try:
        return signing.loads(token, salt=ORDER_SALT)
    except signing.BadSignature as exc:
        raise InvalidToken("Order link is not valid.") from exc
