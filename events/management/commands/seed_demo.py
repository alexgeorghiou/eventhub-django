"""Create a small, realistic demo conference so the public pages have content."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from events.models import Event, Session, Speaker, Track
from ticketing.models import PromoCode, TicketTier

SPEAKERS = [
    ("Mira Kovac", "Staff engineer, distributed systems"),
    ("Daniel Okafor", "Maintainer of an open-source task queue"),
    ("Lena Fischer", "Frontend architect"),
    ("Tomas Herrera", "Database reliability engineer"),
    ("Aiko Tanaka", "Developer advocate"),
]

PROGRAMME = [
    # (day, start, minutes, title, format, track, speaker index)
    (0, time(9, 0), 45, "Opening keynote: Boring technology, exciting products", "keynote", None, 4),
    (0, time(10, 0), 40, "Row locks, queues and the last seat in the house", "talk", 0, 3),
    (0, time(10, 0), 40, "Server-rendered UIs in 2026", "talk", 1, 2),
    (0, time(11, 0), 90, "Workshop: Celery beyond the tutorial", "workshop", 0, 1),
    (0, time(12, 30), 60, "Lunch", "break", None, None),
    (1, time(9, 30), 40, "Designing idempotent APIs", "talk", 0, 0),
    (1, time(10, 30), 40, "Accessible forms that convert", "talk", 1, 2),
    (1, time(11, 30), 45, "Panel: Running Postgres for a decade", "panel", None, 3),
]


class Command(BaseCommand):
    help = "Seed a demo conference with tracks, speakers, sessions, ticket tiers and a promo code."

    def add_arguments(self, parser):
        parser.add_argument("--days-from-now", type=int, default=30)

    @transaction.atomic
    def handle(self, *args, days_from_now: int, **options):
        if Event.objects.filter(slug="pycon-riverside").exists():
            self.stdout.write("Demo event already exists; nothing to do.")
            return

        tz = timezone.get_current_timezone()
        day0 = (timezone.now() + timedelta(days=days_from_now)).date()

        def at(day: int, t: time) -> datetime:
            return datetime.combine(day0 + timedelta(days=day), t, tzinfo=tz)

        event = Event.objects.create(
            title="PyCon Riverside",
            slug="pycon-riverside",
            tagline="Two days of Python, web and data talks by the river.",
            description="A community-run conference with two tracks, hands-on workshops "
            "and plenty of hallway track.",
            venue="Riverside Conference Centre",
            city="Limassol",
            starts_at=at(0, time(8, 30)),
            ends_at=at(1, time(18, 0)),
            is_published=True,
        )
        tracks = [
            Track.objects.create(event=event, name="Backend", color="#0d6efd", position=0),
            Track.objects.create(event=event, name="Frontend", color="#d63384", position=1),
        ]
        speakers = [Speaker.objects.create(name=n, headline=h) for n, h in SPEAKERS]
        for day, start, minutes, title, fmt, track, speaker in PROGRAMME:
            begins = at(day, start)
            session = Session.objects.create(
                event=event,
                track=tracks[track] if track is not None else None,
                title=title,
                format=fmt,
                room="Hall A" if track in (None, 0) else "Hall B",
                starts_at=begins,
                ends_at=begins + timedelta(minutes=minutes),
            )
            if speaker is not None:
                session.speakers.add(speakers[speaker])

        early = TicketTier.objects.create(
            event=event, name="Early bird", price=Decimal("79.00"), capacity=50, position=0
        )
        TicketTier.objects.create(
            event=event, name="Standard", price=Decimal("129.00"), capacity=300, position=1
        )
        TicketTier.objects.create(
            event=event, name="Student", price=Decimal("29.00"), capacity=40, position=2,
            description="Valid student ID required at the door",
        )
        promo = PromoCode.objects.create(
            event=event, code="COMMUNITY20", amount=Decimal("20"), max_uses=100
        )
        promo.tiers.add(early)
        self.stdout.write(self.style.SUCCESS(f"Created demo event at /events/{event.slug}/"))
