from django.contrib import admin
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils.html import format_html

from ticketing.models import PromoCode, TicketTier

from .models import Event, Session, Speaker, Track


class TrackInline(admin.TabularInline):
    model = Track
    extra = 0


class TicketTierInline(admin.TabularInline):
    model = TicketTier
    extra = 0
    fields = ("name", "price", "currency", "capacity", "quantity_sold", "sales_start",
              "sales_end", "is_active", "position")
    readonly_fields = ("quantity_sold",)


class PromoCodeInline(admin.TabularInline):
    model = PromoCode
    extra = 0
    fields = ("code", "discount_type", "amount", "max_uses", "times_used", "valid_until",
              "is_active")
    readonly_fields = ("times_used",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "city", "starts_at", "is_published", "sales_progress", "checkin_link")
    list_filter = ("is_published", "city")
    search_fields = ("title", "venue", "city")
    prepopulated_fields = {"slug": ("title",)}
    date_hierarchy = "starts_at"
    inlines = [TrackInline, TicketTierInline, PromoCodeInline]
    actions = ["publish", "unpublish", "send_reminders_now"]
    fieldsets = (
        (None, {"fields": ("title", "slug", "tagline", "description", "is_published")}),
        ("Where & when", {"fields": ("venue", "city", "starts_at", "ends_at")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_sold=Sum("tiers__quantity_sold"), _capacity=Sum("tiers__capacity"))
        )

    @admin.display(description="Sold")
    def sales_progress(self, obj: Event) -> str:
        sold, capacity = obj._sold or 0, obj._capacity or 0
        pct = round(100 * sold / capacity) if capacity else 0
        return format_html(
            '<div style="width:120px;background:#e9ecef;border-radius:4px">'
            '<div style="width:{}%;background:#198754;color:#fff;font-size:11px;'
            'padding:0 4px;border-radius:4px;white-space:nowrap">{} / {}</div></div>',
            pct, sold, capacity,
        )

    @admin.display(description="Door")
    def checkin_link(self, obj: Event) -> str:
        url = reverse("checkin:scanner", kwargs={"slug": obj.slug})
        return format_html('<a href="{}">Open scanner</a>', url)

    @admin.action(description="Publish selected events")
    def publish(self, request, queryset):
        updated = queryset.update(is_published=True)
        self.message_user(request, f"Published {updated} event(s).")

    @admin.action(description="Unpublish selected events")
    def unpublish(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(request, f"Unpublished {updated} event(s).")

    @admin.action(description="Send attendee reminder emails now")
    def send_reminders_now(self, request, queryset):
        from ticketing.tasks import send_reminders_for_event

        for event in queryset:
            send_reminders_for_event.delay(event.pk)
        self.message_user(request, f"Queued reminders for {queryset.count()} event(s).")


@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    list_display = ("name", "headline", "session_count")
    search_fields = ("name", "headline")
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_sessions=Count("sessions"))

    @admin.display(description="Sessions", ordering="_sessions")
    def session_count(self, obj: Speaker) -> int:
        return obj._sessions


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "track", "format", "room", "starts_at", "ends_at")
    list_filter = ("event", "format", "level", "track")
    search_fields = ("title", "abstract", "speakers__name")
    autocomplete_fields = ("speakers",)
    list_select_related = ("event", "track")
