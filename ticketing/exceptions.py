"""Domain errors raised by the ticketing services.

Each carries a stable ``code`` so the API and the HTML views can map them to
responses without string matching.
"""


class TicketingError(Exception):
    code = "ticketing_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SalesClosed(TicketingError):
    code = "sales_closed"


class InsufficientCapacity(TicketingError):
    code = "insufficient_capacity"


class InvalidPromoCode(TicketingError):
    code = "invalid_promo_code"


class InvalidQuantity(TicketingError):
    code = "invalid_quantity"


class OrderNotCancellable(TicketingError):
    code = "order_not_cancellable"
