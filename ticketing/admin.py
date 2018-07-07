import csv

from django.contrib import admin, messages
from django.http import HttpResponse

from .exceptions import TicketingError
from .models import Order, PromoCode, Ticket, TicketTier
from .services import cancel_order


@admin.register(TicketTier)
class TicketTierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "event",
        "price",
        "currency",
        "capacity",
        "quantity_sold",
        "remaining",
        "is_active",
    )
    list_filter = ("event", "is_active")
    readonly_fields = ("quantity_sold",)
    list_select_related = ("event",)


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "event",
        "discount_type",
        "amount",
        "times_used",
        "max_uses",
        "valid_until",
        "is_active",
    )
    list_filter = ("event", "discount_type", "is_active")
    search_fields = ("code",)
    readonly_fields = ("times_used",)
    filter_horizontal = ("tiers",)


class TicketInline(admin.TabularInline):
    model = Ticket
    extra = 0
    can_delete = False
    fields = ("short_code", "attendee_name", "attendee_email", "status", "checked_in_at")
    readonly_fields = ("short_code", "status", "checked_in_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "event",
        "buyer_name",
        "buyer_email",
        "tier",
        "quantity",
        "total",
        "status",
        "created_at",
    )
    list_filter = ("status", "event", "tier")
    search_fields = ("reference", "buyer_name", "buyer_email", "tickets__attendee_email")
    date_hierarchy = "created_at"
    list_select_related = ("event", "tier")
    inlines = [TicketInline]
    actions = ["cancel_orders"]
    readonly_fields = (
        "reference",
        "event",
        "tier",
        "promo_code",
        "user",
        "quantity",
        "unit_price",
        "discount_total",
        "total",
        "currency",
        "status",
        "created_at",
        "cancelled_at",
        "confirmation_sent_at",
    )

    def has_add_permission(self, request) -> bool:
        # Orders are created through the purchase flow so capacity is enforced.
        return False

    @admin.action(description="Cancel selected orders and release seats")
    def cancel_orders(self, request, queryset):
        cancelled = 0
        for order in queryset:
            try:
                cancel_order(order)
                cancelled += 1
            except TicketingError as exc:
                self.message_user(request, f"{order.reference}: {exc.message}", messages.WARNING)
        if cancelled:
            self.message_user(request, f"Cancelled {cancelled} order(s).", messages.SUCCESS)


class CheckedInFilter(admin.SimpleListFilter):
    title = "checked in"
    parameter_name = "checked_in"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(checked_in_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(checked_in_at__isnull=True)
        return queryset


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "short_code",
        "attendee_name",
        "attendee_email",
        "tier",
        "status",
        "checked_in_at",
    )
    list_filter = ("status", CheckedInFilter, "tier__event", "tier")
    search_fields = ("attendee_name", "attendee_email", "order__reference")
    list_select_related = ("tier", "tier__event")
    readonly_fields = (
        "code",
        "order",
        "tier",
        "checked_in_at",
        "checked_in_by",
        "reminder_sent_at",
    )
    actions = ["export_csv"]

    @admin.action(description="Export attendees as CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="attendees.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["event", "tier", "ticket", "name", "email", "order", "status", "checked_in_at"]
        )
        for t in queryset.select_related("tier__event", "order"):
            writer.writerow(
                [
                    t.tier.event.title,
                    t.tier.name,
                    t.short_code,
                    t.attendee_name,
                    t.attendee_email,
                    t.order.reference,
                    t.status,
                    t.checked_in_at.isoformat() if t.checked_in_at else "",
                ]
            )
        return response
