from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from checkin.qr import qr_png, qr_svg_data_uri
from checkin.tokens import (
    InvalidToken,
    make_order_token,
    make_ticket_token,
    read_order_token,
    read_ticket_token,
)
from events.models import Event

from . import services
from .exceptions import TicketingError
from .forms import PurchaseForm
from .models import Order, Ticket


def register(request, slug: str):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    if event.has_ended:
        messages.info(request, "This event has already taken place.")
        return redirect(event)

    form = PurchaseForm(request.POST or None, event=event,
                        initial={"tier": request.GET.get("tier")})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            order = services.purchase_tickets(
                tier_id=data["tier"].pk,
                quantity=data["quantity"],
                buyer_name=data["buyer_name"],
                buyer_email=data["buyer_email"],
                promo_code=data["promo_code"],
                user=request.user,
            )
        except TicketingError as exc:
            field = "promo_code" if exc.code == "invalid_promo_code" else None
            form.add_error(field, exc.message)
        else:
            messages.success(request, "You're registered! A confirmation email is on its way.")
            return redirect("ticketing:order", token=make_order_token(order))
    return render(request, "ticketing/register.html", {"event": event, "form": form})


@never_cache
def order_detail(request, token: str):
    try:
        reference = read_order_token(token)
    except InvalidToken:
        raise Http404("Order not found") from None
    order = get_object_or_404(
        Order.objects.select_related("event", "tier", "promo_code"), reference=reference
    )
    tickets = []
    for ticket in order.tickets.select_related("tier"):
        ticket_token = make_ticket_token(ticket)
        tickets.append({"ticket": ticket, "token": ticket_token,
                        "qr": qr_svg_data_uri(ticket_token)})
    return render(request, "ticketing/order_detail.html",
                  {"order": order, "event": order.event, "tickets": tickets})


@require_GET
def ticket_qr(request, token: str):
    """PNG QR for a ticket, suitable for wallets, printing or email clients."""
    try:
        claim = read_ticket_token(token)
    except InvalidToken:
        raise Http404("Ticket not found") from None
    if not Ticket.objects.filter(code=claim.ticket_code).exists():
        raise Http404("Ticket not found")
    response = HttpResponse(qr_png(token), content_type="image/png")
    response["Cache-Control"] = "private, max-age=86400"
    return response
