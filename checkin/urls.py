from django.urls import path

from . import views

app_name = "checkin"

urlpatterns = [
    path("<slug:slug>/", views.scanner, name="scanner"),
]
