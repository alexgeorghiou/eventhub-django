from django import forms
from django.conf import settings

from .models import TicketTier


class PurchaseForm(forms.Form):
    tier = forms.ModelChoiceField(
        queryset=TicketTier.objects.none(), empty_label=None, widget=forms.RadioSelect
    )
    quantity = forms.IntegerField(min_value=1, initial=1)
    buyer_name = forms.CharField(label="Your name", max_length=150)
    buyer_email = forms.EmailField(label="Email")
    promo_code = forms.CharField(label="Promo code", max_length=40, required=False)

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        self.fields["tier"].queryset = event.tiers.filter(is_active=True)
        self.fields["tier"].label_from_instance = self._tier_label
        self.fields["quantity"].max_value = settings.EVENTHUB["MAX_TICKETS_PER_ORDER"]
        self.fields["quantity"].widget.attrs["max"] = self.fields["quantity"].max_value
        for name, field in self.fields.items():
            if name != "tier":
                field.widget.attrs.setdefault("class", "form-control")

    @staticmethod
    def _tier_label(tier: TicketTier) -> str:
        suffix = "sold out" if tier.is_sold_out else f"{tier.remaining} left"
        return f"{tier.name} - {tier.price} {tier.currency} ({suffix})"

    def clean_quantity(self) -> int:
        quantity = self.cleaned_data["quantity"]
        limit = settings.EVENTHUB["MAX_TICKETS_PER_ORDER"]
        if quantity > limit:
            raise forms.ValidationError(f"At most {limit} tickets per order.")
        return quantity
