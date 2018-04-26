from django.contrib import admin

from .models import ScanLog


@admin.register(ScanLog)
class ScanLogAdmin(admin.ModelAdmin):
    list_display = ("scanned_at", "event", "result", "ticket", "scanned_by")
    list_filter = ("result", "event")
    list_select_related = ("event", "ticket", "scanned_by")
    date_hierarchy = "scanned_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
