"""SDK exception hierarchy, mapped 1:1 from gateway error codes.

See ``docs/errors/errors.v1.json``.
"""

from __future__ import annotations


class TelloError(Exception):
    """Base class for all Tello SDK errors.

    ``code`` is the gateway error code this was built from, when there was one.
    Branch on it rather than on the message: the message is display text the
    gateway may reword, the code is the contract.
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ConnectionClosedError(TelloError):
    """The WebSocket connection is closed or was never established."""


class SessionReplacedError(TelloError):
    """The connection was displaced by another session (gateway close 4429)."""


class AuthenticationError(TelloError):
    """Connection auth failed (gateway code ``unauthenticated`` / close 4401)."""


class ValidationError(TelloError):
    """A command was rejected as invalid (for example ``toRequired``)."""


class CallAlreadyActiveError(TelloError):
    """A call is already active on this connection (``callAlreadyActive``)."""


class NoActiveCallError(TelloError):
    """No active call for the attempted command (``noActiveCall``)."""


class CallRejectedError(TelloError):
    """The call was rejected by intent validation (``callRejected``).

    ``question`` carries the clarifying question the gateway returned.
    """

    def __init__(
        self, message: str, question: str | None = None, code: str | None = None
    ) -> None:
        super().__init__(message, code)
        self.question = question


class CallRefusedError(TelloError):
    """``create_call`` was refused by an account policy gate.

    Raised before any call exists: no ``call.created``, no call id, no charge.
    The account owner can act on ``insufficientCredit``, ``callerNotVerified``
    and ``noRepresentativeNumber``; only ``concurrentLimitExceeded`` can succeed
    on a later attempt. The gateway never retries, so any retry policy is the
    caller's. Branch on ``code``.
    """


class CallProviderError(TelloError):
    """``create_call`` was refused by a condition on the service side.

    The caller did not cause it and cannot fix it. ``callProviderDraining`` and
    ``callProviderUnavailable`` may succeed later; the other two will not.
    """


class TelloServerError(TelloError):
    """Gateway-side internal error (``internalError``)."""


_CODE_TO_EXCEPTION: dict[str, type[TelloError]] = {
    "unauthenticated": AuthenticationError,
    "callAlreadyActive": CallAlreadyActiveError,
    "toRequired": ValidationError,
    "callIdRequired": ValidationError,
    "callNotFound": ValidationError,
    "callNotCompleted": ValidationError,
    "noActiveCall": NoActiveCallError,
    "dtmfDigitsRequired": ValidationError,
    "dtmfDigitsInvalid": ValidationError,
    "callRejected": CallRejectedError,
    "insufficientCredit": CallRefusedError,
    "concurrentLimitExceeded": CallRefusedError,
    "callerNotVerified": CallRefusedError,
    "noRepresentativeNumber": CallRefusedError,
    "callProviderUnauthorized": CallProviderError,
    "callProviderDraining": CallProviderError,
    "callProviderUnavailable": CallProviderError,
    "callSetupFailed": CallProviderError,
    "internalError": TelloServerError,
}


def exception_for(code: str, message: str, question: str | None = None) -> TelloError:
    """Build the SDK exception for a gateway error ``code``."""
    exc_type = _CODE_TO_EXCEPTION.get(code, TelloServerError)
    if exc_type is CallRejectedError:
        return CallRejectedError(message, question=question, code=code)
    return exc_type(message, code)
