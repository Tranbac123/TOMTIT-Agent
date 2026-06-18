from __future__ import annotations


class ToolRegistryError(Exception):
    pass


class DuplicateToolError(ToolRegistryError):
    pass


class UnknownToolError(ToolRegistryError):
    pass


class InvalidToolSpecError(ToolRegistryError):
    pass


class UnsupportedToolExecutionPolicyError(ToolRegistryError):
    pass
