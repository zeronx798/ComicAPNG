"""Controlled source-plugin errors shared by the GUI and Plugin Host."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PluginErrorCode(StrEnum):
    NETWORK_ERROR = "NetworkError"
    SOURCE_UNAVAILABLE = "SourceUnavailable"
    NOT_FOUND = "NotFound"
    AUTHENTICATION_REQUIRED = "AuthenticationRequired"
    PARTIAL_DOWNLOAD = "PartialDownload"
    CANCELLED = "Cancelled"
    INVALID_SOURCE_DATA = "InvalidSourceData"
    DEPENDENCY_UNAVAILABLE = "DependencyUnavailable"
    INVALID_REQUEST = "InvalidRequest"
    INCOMPATIBLE_API = "IncompatibleApi"
    INTERNAL_PLUGIN_ERROR = "InternalPluginError"


@dataclass(frozen=True, slots=True)
class PluginError:
    code: PluginErrorCode
    message: str
    details: str | None = None
    retryable: bool = False

    @classmethod
    def from_dict(cls, value: object) -> PluginError:
        if not isinstance(value, dict):
            raise ValueError("Plugin error must be an object")
        try:
            code = PluginErrorCode(str(value.get("code")))
        except ValueError as exc:
            raise ValueError("Plugin error has an unknown code") from exc
        message = value.get("message")
        details = value.get("details")
        retryable = value.get("retryable", False)
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Plugin error message must not be empty")
        if details is not None and not isinstance(details, str):
            raise ValueError("Plugin error details must be a string")
        if not isinstance(retryable, bool):
            raise ValueError("Plugin error retryable flag must be a boolean")
        return cls(code, message.strip(), details, retryable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class PluginOperationError(Exception):
    """Raised inside a plugin when an expected controlled failure occurs."""

    def __init__(self, error: PluginError) -> None:
        super().__init__(error.message)
        self.error = error


class PluginCallError(Exception):
    """Raised by the GUI-side host client for a failed RPC response."""

    def __init__(self, error: PluginError) -> None:
        super().__init__(error.message)
        self.error = error
