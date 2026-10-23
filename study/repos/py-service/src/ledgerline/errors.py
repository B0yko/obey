# SPDX-License-Identifier: Apache-2.0
"""Exception types raised by ledgerline."""


class LedgerlineError(Exception):
    """Base class for every error raised on purpose by this package."""


class ValidationError(LedgerlineError, ValueError):
    """Input failed a business rule or could not be parsed."""


class PayloadError(ValidationError):
    """An incoming webhook payload is missing fields or has the wrong shape."""


class NotFoundError(LedgerlineError, LookupError):
    """A record that was asked for does not exist."""


class InsufficientStockError(LedgerlineError):
    """A stock-tracked line asks for more units than are on hand."""


class InvalidTransitionError(LedgerlineError):
    """An invoice was moved to a status it cannot reach from its current one."""
