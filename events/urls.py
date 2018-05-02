from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.EventListView.as_view(), name="list"),
    path("events/<slug:slug>/", views.EventDetailView.as_view(), name="detail"),
    path("speakers/<slug:slug>/", views.SpeakerDetailView.as_view(), name="speaker"),
]
