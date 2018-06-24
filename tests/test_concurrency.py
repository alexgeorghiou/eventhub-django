"""Race the purchase service against itself on a real database.

SQLite serialises all writers, so the interesting behaviour (row locks under
real concurrency) is only exercised on PostgreSQL; CI runs these against a
Postgres service container.
"""

import threading
from decimal import Decimal

import pytest
from django.db import connection, connections

from ticketing.exceptions import InsufficientCapacity, InvalidPromoCode
from ticketing.models import PromoCode, Ticket, TicketTier
from ticketing.services import purchase_tickets

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs PostgreSQL row locks"),
]


def _race(n_threads: int, **purchase_kwargs) -> tuple[int, int]:
    barrier = threading.Barrier(n_threads)
    results: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            barrier.wait()
            purchase_tickets(quantity=1, buyer_name=f"Buyer {i}",
                             buyer_email=f"buyer{i}@example.com", **purchase_kwargs)
            outcome = "ok"
        except InsufficientCapacity:
            outcome = "sold_out"
        except Exception as exc:  # noqa: BLE001 - surfaced through the assertion below
            outcome = repr(exc)
        finally:
            connections.close_all()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    unexpected = [r for r in results if r not in ("ok", "sold_out")]
    assert not unexpected, unexpected
    return results.count("ok"), results.count("sold_out")


def test_concurrent_buyers_cannot_oversell(tier):
    ok, sold_out = _race(12, tier_id=tier.pk)
    tier.refresh_from_db()
    assert ok == tier.capacity == 5
    assert sold_out == 7
    assert tier.quantity_sold == 5
    assert Ticket.objects.filter(tier=tier).count() == 5


def test_concurrent_promo_redemptions_respect_max_uses(event):
    big = TicketTier.objects.create(event=event, name="Big", price=Decimal("10"), capacity=100)
    promo = PromoCode.objects.create(event=event, code="ONCE", amount=Decimal("50"), max_uses=3)
    rejected: list[str] = []
    def worker(i: int) -> None:
        try:
            purchase_tickets(tier_id=big.pk, quantity=1, buyer_name="B",
                             buyer_email=f"p{i}@example.com", promo_code="ONCE")
        except InvalidPromoCode:
            rejected.append("used_up")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    promo.refresh_from_db()
    assert promo.times_used == 3
    assert len(rejected) == 5
