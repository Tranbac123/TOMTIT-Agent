from __future__ import annotations


class ConfirmedWriteError(RuntimeError):
    """Base class for M7-A confirmed-decision write failures."""


class ConfirmedWriteValidationError(ConfirmedWriteError):
    """Policy/input validation rejected the confirmed operation before any client access."""


class ConfirmedWriteBackendError(ConfirmedWriteError):
    """A remote-memory backend error occurred during a required write.

    Always raised with ``raise ... from exc`` so the original typed
    transport/contract/configuration cause is preserved in ``__cause__``.
    """


class RequiredWriteConsistencyError(ConfirmedWriteError):
    """The required-write response could not be reduced to exactly one decision outcome."""


def wrap_backend_error(message: str, cause: BaseException) -> ConfirmedWriteBackendError:
    """Return a ``ConfirmedWriteBackendError`` whose ``__cause__`` is the original error.

    Uses the ``raise ... from exc`` idiom so the original typed transport/contract cause
    is preserved (and context is suppressed) for safe diagnostic logging. The caller logs
    this object rather than re-raising it; the confirmed-save run still ends FAILED.
    """
    try:
        raise ConfirmedWriteBackendError(message) from cause
    except ConfirmedWriteBackendError as wrapped:
        return wrapped
