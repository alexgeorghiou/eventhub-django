from django.urls import path

from . import views

app_name = "ticketing"

urlpatterns = [
    path("events/<slug:slug>/register/", views.register, name="register"),
    path("orders/<str:token>/", views.order_detail, name="order"),
    path("tickets/<str:token>/qr.png", views.ticket_qr, name="ticket-qr"),
]
