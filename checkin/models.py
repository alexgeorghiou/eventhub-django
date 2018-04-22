from django.conf import settings
from django.db import models

from events.models import Event


class ScanResult(models.TextChoices):
    ADMITTED = "admitted", "Admitted"
    ALREADY_CHECKED_IN = "already_checked_in", "Already checked in"
    CANCELLED = "cancelled", "Ticket cancelled"
    WRONG_EVENT = "wrong_event", "Ticket is for another event"
    INVALID = "invalid", "Invalid code"


class ScanLog(models.Model):
    """Audit trail of every scan at the door, successful or not."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="scans")
    ticket = models.ForeignKey(
        "ticketing.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="scans"
    )
    result = models.CharField(max_length=24, choices=ScanResult.choices)
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scanned_at"]
        indexes = [models.Index(fields=["event", "-scanned_at"])]

    def __str__(self) -> str:
        return f"{self.get_result_display()} @ {self.scanned_at:%Y-%m-%d %H:%M}"
