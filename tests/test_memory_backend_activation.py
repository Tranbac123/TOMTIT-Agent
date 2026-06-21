from __future__ import annotations

import pytest

from agent_core.memory.errors import RemoteMemoryConfigurationError
from agent_core.memory.factory import (
    MemoryBackend,
    MemoryBackendConfig,
    build_memory_backend,
    validate_memory_activation,
)
from agent_core.memory.local_client import LocalMemoryClient
from agent_core.memory.null_client import NullMemoryClient
from agent_core.memory.remote_client import RemoteMemoryClient
from agent_core.runtime.runtime_agent import build_agent_with_memory_backend
from agent_core.state.enums import ToolName
from agent_core.state.session_state import TurnRecord
from agent_core.tools.registry import (
    CONTEXT_CONSUMER_TOOLS,
    LOCAL_DURABLE_TOOLS,
    NON_MEMORY_TOOLS,
    build_tool_registry,
)


def test_local_backend_uses_local_client_and_keeps_local_durable_tools():
    config = MemoryBackendConfig.from_values(backend="local")
    components = build_memory_backend(config)
    registry = build_tool_registry(disabled_tools=components.disabled_tools)

    assert config.backend is MemoryBackend.LOCAL
    assert isinstance(components.memory_client, LocalMemoryClient)
    assert components.disabled_tools == frozenset()
    assert all(tool in registry for tool in LOCAL_DURABLE_TOOLS)


def test_remote_backend_uses_remote_client_and_filters_local_durable_tools():
    config = MemoryBackendConfig.from_values(
        backend="remote",
        base_url="http://127.0.0.1:8077",
        project_id="tomtit-agent",
        default_user_id="local-user",
    )
    components = build_memory_backend(config)
    registry = build_tool_registry(disabled_tools=components.disabled_tools)

    assert isinstance(components.memory_client, RemoteMemoryClient)
    assert all(tool not in registry for tool in LOCAL_DURABLE_TOOLS)
    assert ToolName.ANSWER_FROM_CONTEXT in registry
    validate_memory_activation(memory_client=components.memory_client, tools=registry)
    components.memory_client.close()


def test_none_backend_uses_noop_client_and_filters_local_durable_tools():
    components = build_memory_backend(MemoryBackendConfig.from_values(backend="none"))
    registry = build_tool_registry(disabled_tools=components.disabled_tools)

    assert isinstance(components.memory_client, NullMemoryClient)
    assert all(tool not in registry for tool in LOCAL_DURABLE_TOOLS)
    assert ToolName.ANSWER_FROM_CONTEXT in registry
    response = components.memory_client.write_memory_candidates([], task_id="task")
    assert response.written_ids == []
    assert response.skipped == []
    validate_memory_activation(memory_client=components.memory_client, tools=registry)


def test_invalid_backend_rejected():
    with pytest.raises(RemoteMemoryConfigurationError):
        MemoryBackendConfig.from_values(backend="invalid")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": None, "project_id": "p", "default_user_id": "u"},
        {"base_url": "http://127.0.0.1:8077", "project_id": None, "default_user_id": "u"},
        {"base_url": "http://127.0.0.1:8077", "project_id": "p", "default_user_id": None},
    ],
)
def test_remote_missing_config_rejected(kwargs):
    config = MemoryBackendConfig.from_values(backend="remote", **kwargs)
    with pytest.raises(RemoteMemoryConfigurationError):
        build_memory_backend(config)


def test_forced_mixed_remote_and_local_durable_tools_hard_fails():
    remote = RemoteMemoryClient(
        base_url="http://127.0.0.1:8077",
        project_id="tomtit-agent",
        default_user_id="local-user",
    )
    try:
        registry = build_tool_registry()
        with pytest.raises(RemoteMemoryConfigurationError):
            validate_memory_activation(memory_client=remote, tools=registry)
    finally:
        remote.close()


def test_build_agent_with_remote_backend_has_safe_tool_set():
    config = MemoryBackendConfig.from_values(
        backend="remote",
        base_url="http://127.0.0.1:8077",
        project_id="tomtit-agent",
        default_user_id="local-user",
    )
    agent, _store = build_agent_with_memory_backend(memory_config=config)
    try:
        assert isinstance(agent.memory_client, RemoteMemoryClient)
        assert all(tool not in agent.tools for tool in LOCAL_DURABLE_TOOLS)
        assert ToolName.ANSWER_FROM_CONTEXT in agent.tools
    finally:
        agent.memory_client.close()


def test_tool_classification_covers_all_current_builtins():
    classified = LOCAL_DURABLE_TOOLS | CONTEXT_CONSUMER_TOOLS | NON_MEMORY_TOOLS
    assert classified == set(ToolName)
    assert LOCAL_DURABLE_TOOLS.isdisjoint(CONTEXT_CONSUMER_TOOLS)
    assert ToolName.ANSWER_FROM_CONTEXT in CONTEXT_CONSUMER_TOOLS


def test_session_state_schema_unchanged_by_backend_activation():
    assert set(TurnRecord.__dataclass_fields__) == {
        "task_id",
        "goal",
        "final_answer",
        "status",
        "planned_actions",
        "memory_degraded",
        "memory_write_failed",
        "disclosure_reasons",
        "completed_at",
    }


def test_backend_client_required_write_capability_values():
    from agent_core.memory.local_client import LocalMemoryClient
    from agent_core.memory.null_client import NullMemoryClient
    from agent_core.memory.in_memory_store import InMemoryStore

    assert LocalMemoryClient(InMemoryStore()).supports_required_write is False
    assert NullMemoryClient().supports_required_write is False


def test_null_client_write_accepts_request_id_kwarg():
    from agent_core.memory.null_client import NullMemoryClient

    resp = NullMemoryClient().write_memory_candidates([], request_id="memory-write:conf-1")
    assert resp.written_ids == []
