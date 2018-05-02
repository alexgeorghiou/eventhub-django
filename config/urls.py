from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok"})


admin.site.site_header = "EventHub administration"
admin.site.site_title = "EventHub"
admin.site.index_title = "Events, tickets & check-in"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("config.api_urls")),
    path("healthz", healthz, name="healthz"),
    path("checkin/", include("checkin.urls")),
    path("", include("ticketing.urls")),
    path("", include("events.urls")),
]
