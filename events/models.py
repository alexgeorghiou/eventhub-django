from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class EventQuerySet(models.QuerySet["Event"]):
    def published(self) -> EventQuerySet:
        return self.filter(is_published=True)

    def upcoming(self) -> EventQuerySet:
        return self.filter(ends_at__gte=timezone.now())


class Event(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    tagline = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    venue = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                check=Q(ends_at__gt=models.F("starts_at")), name="event_ends_after_start"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.title)[:200] or "event"
        candidate, n = base, 2
        while Event.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def clean(self) -> None:
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "An event must end after it starts."})

    def get_absolute_url(self) -> str:
        return reverse("events:detail", kwargs={"slug": self.slug})

    @property
    def has_ended(self) -> bool:
        return self.ends_at < timezone.now()


class Track(models.Model):
    """A parallel stream of sessions, e.g. "Backend" or "Main stage"."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#0d6efd", help_text="Hex colour, e.g. #0d6efd")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["event", "position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["event", "name"], name="unique_track_per_event"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.event})"


class Speaker(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    headline = models.CharField(max_length=200, blank=True, help_text="Role and company")
    bio = models.TextField(blank=True)
    website = models.URLField(blank=True)
    photo_url = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base = slugify(self.name) or "speaker"
            candidate, n = base, 2
            while Speaker.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class Session(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    class Format(models.TextChoices):
        TALK = "talk", "Talk"
        WORKSHOP = "workshop", "Workshop"
        KEYNOTE = "keynote", "Keynote"
        PANEL = "panel", "Panel"
        BREAK = "break", "Break"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sessions")
    track = models.ForeignKey(
        Track, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions"
    )
    title = models.CharField(max_length=200)
    abstract = models.TextField(blank=True)
    format = models.CharField(max_length=20, choices=Format.choices, default=Format.TALK)
    level = models.CharField(max_length=20, choices=Level.choices, blank=True)
    room = models.CharField(max_length=100, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    speakers = models.ManyToManyField(Speaker, related_name="sessions", blank=True)

    class Meta:
        ordering = ["starts_at", "track__position"]
        constraints = [
            models.CheckConstraint(
                check=Q(ends_at__gt=models.F("starts_at")), name="session_ends_after_start"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "A session must end after it starts."
        if self.event_id and self.starts_at and self.ends_at:
            event = self.event
            if self.starts_at < event.starts_at or self.ends_at > event.ends_at:
                errors["starts_at"] = "Sessions must take place within the event's dates."
        if self.track_id and self.event_id and self.track.event_id != self.event_id:
            errors["track"] = "Track belongs to a different event."
        if self.room and self.event_id and self.starts_at and self.ends_at:
            clash = (
                Session.objects.filter(
                    event_id=self.event_id,
                    room__iexact=self.room,
                    starts_at__lt=self.ends_at,
                    ends_at__gt=self.starts_at,
                )
                .exclude(pk=self.pk)
                .first()
            )
            if clash:
                errors["room"] = f"Room is already booked for '{clash.title}'."
        if errors:
            raise ValidationError(errors)
