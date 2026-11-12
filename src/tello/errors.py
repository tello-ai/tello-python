"""SDK exception hierarchy.

WebSocket errors map 1:1 from gateway error codes (see
``docs/errors/errors.v1.json``); REST errors are :class:`TelloApiError` and
:class:`TelloApiConnectionError`.
"""

from __future__ import annotations

from typing import Any


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
    """Connection auth failed: the server key was refused (``unauthenticated``),
    the connection is outside the key's allowed IP list (``ipNotAllowed``), a
    close 4401, or no ``auth.ok`` in time.

    ``ip`` is the connection address the gateway judged for ``ipNotAllowed``
    (``None`` when it could not prove one, or for other causes).
    """

    def __init__(
        self, message: str, code: str | None = None, ip: str | None = None
    ) -> None:
        super().__init__(message, code)
        self.ip = ip


class PermissionDeniedError(TelloError):
    """The server key lacks the scope a command needs (``insufficientScope``).

    Only that command is refused; the connection stays open. ``required_scope``
    is the scope the command needs (for example ``calls:write``). Not to be
    confused with Python's built-in ``PermissionError``.
    """

    def __init__(
        self, message: str, code: str | None = None, required_scope: str | None = None
    ) -> None:
        super().__init__(message, code)
        self.required_scope = required_scope


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


class TelloApiError(TelloError):
    """The REST API (:class:`tello.TelloApi`) answered with an error.

    ``code`` is the envelope's ``error`` exactly as sent, in snake_case
    (``tool_not_found``, ``insufficient_scope``, …), so it matches the public
    error table. Branch on ``code`` and ``status``, not on ``message``.

    - An error response that is not the JSON envelope (a proxy page, for
      example) has ``code = "http_<status>"``, the HTTP reason phrase as
      ``message`` and ``data = None``.
    - A success status the API does not document for the method, or a
      success body that is not a JSON object, has ``code = "invalid_response"``.

    ``data`` is the envelope's ``data`` object (``None`` when absent).
    ``idempotency_key`` is the ``Idempotency-Key`` the request carried, or
    ``None``; resend with the same key to retry the same request.
    """

    code: str

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        super().__init__(message, code)
        self.status = status
        self.message = message
        self.data = data
        self.idempotency_key = idempotency_key


class TelloApiConnectionError(TelloError):
    """A REST request got no response: the connection failed or timed out.

    The cause is kept as ``__cause__``. A write (create, update, delete,
    ``crews.generate``, call draft create/revise/confirm) that fails this way
    **may still have been applied**: check with ``get``/``list`` before
    resending, and resend a create with the same ``idempotency_key`` (kept
    here; ``call_drafts.confirm`` always has one) so it is not done twice.
    """

    def __init__(self, message: str, idempotency_key: str | None = None) -> None:
        super().__init__(message)
        self.idempotency_key = idempotency_key


_CODE_TO_EXCEPTION: dict[str, type[TelloError]] = {
    "unauthenticated": AuthenticationError,
    "ipNotAllowed": AuthenticationError,
    "insufficientScope": PermissionDeniedError,
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


def exception_for(
    code: str,
    message: str,
    question: str | None = None,
    *,
    required_scope: str | None = None,
    ip: str | None = None,
) -> TelloError:
    """Build the SDK exception for a gateway error ``code``.

    ``question``, ``required_scope`` and ``ip`` are the error frame's
    ``question``, ``requiredScope`` and ``ip``; each lands on the exception
    that carries it.
    """
    exc_type = _CODE_TO_EXCEPTION.get(code, TelloServerError)
    if exc_type is CallRejectedError:
        return CallRejectedError(message, question=question, code=code)
    if exc_type is PermissionDeniedError:
        return PermissionDeniedError(message, code, required_scope=required_scope)
    if exc_type is AuthenticationError:
        return AuthenticationError(message, code, ip=ip)
    return exc_type(message, code)
