"""Every gateway error code maps to the class the contract names for it.

Contract: ``docs/errors/errors.v1.json``.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tello import (
    AuthenticationError,
    CallAlreadyActiveError,
    CallProviderError,
    CallRefusedError,
    CallRejectedError,
    NoActiveCallError,
    TelloError,
    TelloServerError,
    ValidationError,
)
from tello.errors import exception_for

CONTRACT = [
    ("unauthenticated", AuthenticationError),
    ("callAlreadyActive", CallAlreadyActiveError),
    ("toRequired", ValidationError),
    ("callIdRequired", ValidationError),
    ("callNotFound", ValidationError),
    ("callNotCompleted", ValidationError),
    ("noActiveCall", NoActiveCallError),
    ("dtmfDigitsRequired", ValidationError),
    ("dtmfDigitsInvalid", ValidationError),
    ("callRejected", CallRejectedError),
    ("insufficientCredit", CallRefusedError),
    ("concurrentLimitExceeded", CallRefusedError),
    ("callerNotVerified", CallRefusedError),
    ("noRepresentativeNumber", CallRefusedError),
    ("callProviderUnauthorized", CallProviderError),
    ("callProviderDraining", CallProviderError),
    ("callProviderUnavailable", CallProviderError),
    ("callSetupFailed", CallProviderError),
    ("internalError", TelloServerError),
]

_CONTRACT_FILE = (
    pathlib.Path(__file__).resolve().parents[1] / "docs" / "errors" / "errors.v1.json"
)


@pytest.mark.parametrize(("code", "expected"), CONTRACT)
def test_maps_every_contract_code(code: str, expected: type[TelloError]) -> None:
    error = exception_for(code, "message")

    assert isinstance(error, expected)
    # Callers branch on code, never on the message: the gateway may reword the
    # message, the code is the contract.
    assert error.code == code


def test_table_matches_the_contract_file() -> None:
    """The generated copy of the contract is the list this table has to cover."""
    contract = json.loads(_CONTRACT_FILE.read_text(encoding="utf-8"))
    declared = [(entry["code"], entry["sdkException"]) for entry in contract["errors"]]

    assert declared == [(code, cls.__name__) for code, cls in CONTRACT]


def test_unknown_code_falls_back_to_server_error() -> None:
    error = exception_for("somethingNewUpstream", "message")

    assert isinstance(error, TelloServerError)
    assert error.code == "somethingNewUpstream"


def test_call_rejected_preserves_question() -> None:
    error = exception_for("callRejected", "Call rejected", "why?")

    assert isinstance(error, CallRejectedError)
    assert error.question == "why?"
    assert error.code == "callRejected"
