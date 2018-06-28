import pytest

from checkin.models import ScanLog, ScanResult
from checkin.qr import qr_png, qr_svg_data_uri
from checkin.services import check_in
from checkin.tokens import (
    InvalidToken,
    make_order_token,
    make_ticket_token,
    read_order_token,
    read_ticket_token,
)
from ticketing.models import TicketTier
from ticketing.services import cancel_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(buy):
    return buy(1).tickets.get()


def test_ticket_token_round_trip(ticket):
    claim = read_ticket_token(make_ticket_token(ticket))
    assert claim.ticket_code == ticket.code
    assert claim.event_id == ticket.tier.event_id


def test_tampered_token_is_rejected(ticket):
    token = make_ticket_token(ticket)
    forged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(InvalidToken):
        read_ticket_token(forged)


def test_garbage_token_is_rejected():
    with pytest.raises(InvalidToken):
        read_ticket_token("not-a-token")


def test_order_token_round_trip(buy):
    order = buy(1)
    assert read_order_token(make_order_token(order)) == order.reference
    with pytest.raises(InvalidToken):
        read_order_token(order.reference)


def test_first_scan_admits(ticket, staff_user):
    outcome = check_in(make_ticket_token(ticket), ticket.tier.event, scanned_by=staff_user)
    assert outcome.admitted
    ticket.refresh_from_db()
    assert ticket.checked_in_at is not None
    assert ticket.checked_in_by == staff_user


def test_second_scan_reports_already_checked_in(ticket, staff_user):
    token = make_ticket_token(ticket)
    check_in(token, ticket.tier.event, scanned_by=staff_user)
    first_time = type(ticket).objects.get(pk=ticket.pk).checked_in_at
    outcome = check_in(token, ticket.tier.event, scanned_by=staff_user)
    assert outcome.result == ScanResult.ALREADY_CHECKED_IN
    assert outcome.ticket.checked_in_at == first_time


def test_ticket_for_another_event(ticket, make_event):
    other = make_event(title="Elsewhere")
    outcome = check_in(make_ticket_token(ticket), other)
    assert outcome.result == ScanResult.WRONG_EVENT


def test_cancelled_ticket_is_refused(buy):
    order = buy(1)
    ticket = order.tickets.get()
    cancel_order(order)
    outcome = check_in(make_ticket_token(ticket), ticket.tier.event)
    assert outcome.result == ScanResult.CANCELLED


def test_signed_token_for_deleted_ticket_is_invalid(ticket):
    token = make_ticket_token(ticket)
    event = ticket.tier.event
    ticket.order.delete()
    assert check_in(token, event).result == ScanResult.INVALID


def test_every_scan_is_logged(ticket, staff_user):
    event = ticket.tier.event
    check_in(make_ticket_token(ticket), event, scanned_by=staff_user)
    check_in(make_ticket_token(ticket), event, scanned_by=staff_user)
    check_in("junk", event, scanned_by=staff_user)
    results = list(ScanLog.objects.order_by("id").values_list("result", flat=True))
    assert results == [ScanResult.ADMITTED, ScanResult.ALREADY_CHECKED_IN, ScanResult.INVALID]


def test_qr_png_and_svg(ticket):
    token = make_ticket_token(ticket)
    assert qr_png(token).startswith(b"\x89PNG\r\n\x1a\n")
    assert qr_svg_data_uri(token).startswith("data:image/svg+xml")


def test_tier_count_unchanged_by_check_in(ticket):
    check_in(make_ticket_token(ticket), ticket.tier.event)
    assert TicketTier.objects.get(pk=ticket.tier_id).quantity_sold == 1
