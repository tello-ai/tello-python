"""SDK exception hierarchy, mapped 1:1 from gateway error codes.

See ``contracts/errors/errors.v1.json``.
"""

from __future__ import annotations


class TelloError(Exception):
    """Base class for all Tello SDK errors."""


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

    def __init__(self, message: str, question: str | None = None) -> None:
        super().__init__(message)
        self.question = question


class TelloServerError(TelloError):
    """Gateway-side internal error (``internalError``)."""


_CODE_TO_EXCEPTION: dict[str, type[TelloError]] = {
    "unauthenticated": AuthenticationError,
    "toRequired": ValidationError,
    "agentIdRequired": ValidationError,
    "callAlreadyActive": CallAlreadyActiveError,
    "noActiveCall": NoActiveCallError,
    "callRejected": CallRejectedError,
    "internalError": TelloServerError,
}


def exception_for(code: str, message: str, question: str | None = None) -> TelloError:
    """Build the SDK exception for a gateway error ``code``."""
    exc_type = _CODE_TO_EXCEPTION.get(code, TelloServerError)
    if exc_type is CallRejectedError:
        return CallRejectedError(message, question=question)
    return exc_type(message)
