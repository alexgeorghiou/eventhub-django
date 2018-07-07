from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from events.models import Event

from .models import ScanLog
from .services import check_in


@staff_member_required
@ensure_csrf_cookie
def scanner(request, slug: str):
    """Door scanner. Uses the browser camera when available, with manual entry as fallback.

    Plain form POSTs are handled here too, so the page works without JavaScript.
    """
    event = get_object_or_404(Event, slug=slug)
    outcome = None
    if request.method == "POST":
        outcome = check_in(request.POST.get("token", ""), event, scanned_by=request.user)
    recent = ScanLog.objects.filter(event=event).select_related("ticket")[:10]
    return render(
        request, "checkin/scanner.html", {"event": event, "outcome": outcome, "recent": recent}
    )
