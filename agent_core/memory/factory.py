from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from agent_core.memory.client import MemoryClientProtocol
from agent_core.memory.errors import RemoteMemoryConfigurationError
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.local_client import LocalMemoryClient
from agent_core.memory.null_client import NullMemoryClient
from agent_core.memory.remote_client import RemoteMemoryClient
from agent_core.state.enums import ToolName
from agent_core.tools.base import ToolSpec
from agent_core.tools.registry import LOCAL_DURABLE_TOOLS


class MemoryBackend(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
    NONE = "none"


@dataclass(frozen=True)
class MemoryBackendConfig:
    backend: MemoryBackend = MemoryBackend.LOCAL
    base_url: str | None = None
    project_id: str | None = None
    default_user_id: str | None = None
    timeout_seconds: float = 5.0

    @classmethod
    def from_values(
        cls,
        *,
        backend: str = "local",
        base_url: str | None = None,
        project_id: str | None = None,
        default_user_id: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> MemoryBackendConfig:
        try:
            parsed_backend = MemoryBackend(backend)
        except ValueError as exc:
            raise RemoteMemoryConfigurationError(
                "memory_backend must be local, remote, or none"
            ) from exc
        return cls(
            backend=parsed_backend,
            base_url=base_url,
            project_id=project_id,
            default_user_id=default_user_id,
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True)
class MemoryBackendComponents:
    memory_client: MemoryClientProtocol | None
    store: InMemoryStore
    disabled_tools: frozenset[ToolName]


def build_memory_backend(config: MemoryBackendConfig) -> MemoryBackendComponents:
    store = InMemoryStore()
    if config.backend is MemoryBackend.LOCAL:
        return MemoryBackendComponents(
            memory_client=LocalMemoryClient(store),
            store=store,
            disabled_tools=frozenset(),
        )
    if config.backend is MemoryBackend.NONE:
        return MemoryBackendComponents(
            memory_client=NullMemoryClient(),
            store=store,
            disabled_tools=LOCAL_DURABLE_TOOLS,
        )
    return MemoryBackendComponents(
        memory_client=RemoteMemoryClient(
            base_url=_required(config.base_url, "memory_base_url"),
            project_id=_required(config.project_id, "memory_project_id"),
            default_user_id=_required(config.default_user_id, "memory_user_id"),
            timeout_seconds=config.timeout_seconds,
        ),
        store=store,
        disabled_tools=LOCAL_DURABLE_TOOLS,
    )


def validate_memory_activation(
    *,
    memory_client: MemoryClientProtocol | None,
    tools: Mapping[ToolName, ToolSpec],
) -> None:
    has_local_durable = any(tool_name in tools for tool_name in LOCAL_DURABLE_TOOLS)
    if isinstance(memory_client, RemoteMemoryClient) and has_local_durable:
        raise RemoteMemoryConfigurationError(
            "remote memory backend cannot activate local durable-memory tools"
        )
    if isinstance(memory_client, NullMemoryClient) and has_local_durable:
        raise RemoteMemoryConfigurationError(
            "none memory backend cannot activate durable-memory tools"
        )


def _required(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise RemoteMemoryConfigurationError(f"{field_name} is required")
    return value
