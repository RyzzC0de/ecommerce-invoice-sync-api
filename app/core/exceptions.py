"""
Custom application exceptions.
"""


class BillingSystemError(Exception):
    """
    Raised when the external billing system call fails (HTTP error or network
    error). Caught in the invoices router and returned as HTTP 502.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
