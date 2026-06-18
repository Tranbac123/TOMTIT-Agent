from __future__ import annotations


class SkillRegistryError(Exception):
    pass


class DuplicateSkillError(SkillRegistryError):
    pass


class DuplicateSkillIntentError(SkillRegistryError):
    pass


class UnknownSkillError(SkillRegistryError):
    pass


class MissingSkillToolError(SkillRegistryError):
    pass


class InvalidSkillSpecError(SkillRegistryError):
    pass


class InvalidSkillPlanError(SkillRegistryError):
    pass
