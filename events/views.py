from collections import defaultdict
from itertools import groupby

from django.utils import timezone
from django.views.generic import DetailView, ListView

from .models import Event, Speaker


class EventListView(ListView):
    template_name = "events/event_list.html"
    context_object_name = "events"
    paginate_by = 12

    def get_queryset(self):
        return Event.objects.published().upcoming().prefetch_related("tiers")


class EventDetailView(DetailView):
    template_name = "events/event_detail.html"
    context_object_name = "event"

    def get_queryset(self):
        qs = Event.objects.all()
        return qs if self.request.user.is_staff else qs.published()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event: Event = self.object
        sessions = event.sessions.select_related("track").prefetch_related("speakers")
        ctx["schedule"] = [
            (day, list(items))
            for day, items in groupby(sessions, key=lambda s: timezone.localdate(s.starts_at))
        ]
        speakers: dict[int, Speaker] = {}
        for session in sessions:
            for speaker in session.speakers.all():
                speakers.setdefault(speaker.pk, speaker)
        ctx["speakers"] = sorted(speakers.values(), key=lambda s: s.name)
        ctx["tiers"] = [t for t in event.tiers.all() if t.is_active]
        return ctx


class SpeakerDetailView(DetailView):
    model = Speaker
    template_name = "events/speaker_detail.html"
    context_object_name = "speaker"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        by_event = defaultdict(list)
        sessions = (
            self.object.sessions.filter(event__is_published=True)
            .select_related("event", "track")
            .order_by("starts_at")
        )
        for session in sessions:
            by_event[session.event].append(session)
        ctx["sessions_by_event"] = dict(by_event)
        return ctx
