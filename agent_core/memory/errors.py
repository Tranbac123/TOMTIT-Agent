from __future__ import annotations


class RemoteMemoryError(Exception):
    """Base class for Agent-side remote memory failures."""


class RemoteMemoryUnavailableError(RemoteMemoryError):
    """Remote memory is temporarily unavailable."""


class RemoteMemoryContractError(RemoteMemoryError):
    """Remote memory violated or rejected the v1 contract."""


class RemoteMemoryConfigurationError(RemoteMemoryError):
    """Remote memory client configuration is invalid or incomplete."""


class RemoteMemoryWriteError(RemoteMemoryError):
    """Remote memory write did not persist candidates."""
