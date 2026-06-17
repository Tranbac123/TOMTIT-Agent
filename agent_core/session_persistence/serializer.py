from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from agent_core.session_persistence.errors import SessionDataCorruptionError
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus
from agent_core.state.session_state import SessionState, TurnRecord


class SessionSerializer:
    SCHEMA_VERSION = "1"
    _ROOT_FIELDS = frozenset(
        {"schema_version", "session_id", "created_at", "updated_at", "turns"}
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def to_dict(cls, session: object) -> dict[str, Any]:
        """Serialize SessionState → dict. Order: isinstance → turns list → uuid
        → aware datetimes → turn dicts → invariants → return."""
        if not isinstance(session, SessionState):
            raise SessionDataCorruptionError(
                f"expected SessionState, got {type(session).__name__}"
            )

        if not isinstance(session.turns, list):
            raise SessionDataCorruptionError("session.turns must be a list")

        cls._require_canonical_uuid(session.session_id)
        cls._require_aware(session.created_at, "created_at")
        cls._require_aware(session.updated_at, "updated_at")

        turn_dicts = [cls._turn_to_dict(t) for t in session.turns]

        result: dict[str, Any] = {
            "schema_version": cls.SCHEMA_VERSION,
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "turns": turn_dicts,
        }

        cls._validate_invariants(session)
        return result

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        expected_session_id: str | None = None,
    ) -> SessionState:
        """Deserialize dict → SessionState. Wraps structural errors as
        SessionDataCorruptionError."""
        try:
            # isinstance BEFORE .get — per spec
            if not isinstance(data, dict):
                raise SessionDataCorruptionError(
                    f"session data must be a dict, got {type(data).__name__}"
                )

            version = data.get("schema_version")
            if version != cls.SCHEMA_VERSION:
                raise SessionDataCorruptionError(
                    f"unsupported schema_version: {version!r}, "
                    f"expected {cls.SCHEMA_VERSION!r}"
                )

            actual_keys = set(data.keys())
            if actual_keys != cls._ROOT_FIELDS:
                extra = actual_keys - cls._ROOT_FIELDS
                missing = cls._ROOT_FIELDS - actual_keys
                raise SessionDataCorruptionError(
                    f"unexpected root fields — extra={extra!r}, missing={missing!r}"
                )

            # _require_canonical_uuid even when expected=None
            session_id = cls._require_canonical_uuid(data["session_id"])

            if expected_session_id is not None:
                expected_canonical = str(uuid.UUID(expected_session_id))
                if session_id != expected_canonical:
                    raise SessionDataCorruptionError(
                        f"session_id mismatch: file has {session_id!r}, "
                        f"expected {expected_canonical!r}"
                    )

            created_at = cls._parse_dt(data["created_at"], "created_at")
            updated_at = cls._parse_dt(data["updated_at"], "updated_at")

            if not isinstance(data["turns"], list):
                raise SessionDataCorruptionError(
                    f"turns must be a list, got {type(data['turns']).__name__}"
                )

            turns = [cls._turn_from_dict(t) for t in data["turns"]]

            session = SessionState(
                session_id=session_id,
                created_at=created_at,
                updated_at=updated_at,
                turns=turns,
            )

            cls._validate_invariants(session)
            return session

        except SessionDataCorruptionError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SessionDataCorruptionError(
                f"session data is corrupt: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Turn serialization
    # ------------------------------------------------------------------

    @classmethod
    def _turn_to_dict(cls, turn: object) -> dict[str, Any]:
        if not isinstance(turn, TurnRecord):
            raise SessionDataCorruptionError(
                f"expected TurnRecord, got {type(turn).__name__}"
            )

        if not isinstance(turn.planned_actions, tuple) or not all(
            isinstance(a, str) for a in turn.planned_actions
        ):
            raise SessionDataCorruptionError(
                "planned_actions must be tuple[str, ...]"
            )

        if not isinstance(turn.disclosure_reasons, tuple) or not all(
            isinstance(r, str) for r in turn.disclosure_reasons
        ):
            raise SessionDataCorruptionError(
                "disclosure_reasons must be tuple[str, ...]"
            )

        if type(turn.memory_degraded) is not bool:
            raise SessionDataCorruptionError(
                f"memory_degraded must be bool, got {type(turn.memory_degraded).__name__}"
            )

        if type(turn.memory_write_failed) is not bool:
            raise SessionDataCorruptionError(
                f"memory_write_failed must be bool, got {type(turn.memory_write_failed).__name__}"
            )

        if not isinstance(turn.status, AgentStatus):
            raise SessionDataCorruptionError(
                f"status must be AgentStatus, got {type(turn.status).__name__}"
            )

        cls._require_aware(turn.completed_at, "completed_at")

        return {
            "task_id": turn.task_id,
            "goal": turn.goal,
            "final_answer": turn.final_answer,
            "status": turn.status.value,
            "planned_actions": list(turn.planned_actions),
            "memory_degraded": turn.memory_degraded,
            "memory_write_failed": turn.memory_write_failed,
            "disclosure_reasons": list(turn.disclosure_reasons),
            "completed_at": turn.completed_at.isoformat(),
        }

    @classmethod
    def _turn_from_dict(cls, data: object) -> TurnRecord:
        if not isinstance(data, dict):
            raise SessionDataCorruptionError(
                f"turn must be a dict, got {type(data).__name__}"
            )

        task_id = data["task_id"]
        if not isinstance(task_id, str):
            raise SessionDataCorruptionError(
                f"task_id must be str, got {type(task_id).__name__}"
            )

        goal = data["goal"]
        if not isinstance(goal, str):
            raise SessionDataCorruptionError(
                f"goal must be str, got {type(goal).__name__}"
            )

        final_answer = data["final_answer"]
        if final_answer is not None and not isinstance(final_answer, str):
            raise SessionDataCorruptionError(
                f"final_answer must be str or None, got {type(final_answer).__name__}"
            )

        status_val = data["status"]
        try:
            status = AgentStatus(status_val)
        except (ValueError, KeyError) as exc:
            raise SessionDataCorruptionError(
                f"invalid status value: {status_val!r}"
            ) from exc

        planned_actions_raw = data["planned_actions"]
        if not isinstance(planned_actions_raw, list) or not all(
            isinstance(a, str) for a in planned_actions_raw
        ):
            raise SessionDataCorruptionError(
                "planned_actions must be a list of str"
            )

        memory_degraded = data["memory_degraded"]
        if not isinstance(memory_degraded, bool):
            raise SessionDataCorruptionError(
                f"memory_degraded must be bool, got {type(memory_degraded).__name__}"
            )

        memory_write_failed = data["memory_write_failed"]
        if not isinstance(memory_write_failed, bool):
            raise SessionDataCorruptionError(
                f"memory_write_failed must be bool, got {type(memory_write_failed).__name__}"
            )

        disclosure_reasons_raw = data["disclosure_reasons"]
        if not isinstance(disclosure_reasons_raw, list) or not all(
            isinstance(r, str) for r in disclosure_reasons_raw
        ):
            raise SessionDataCorruptionError(
                "disclosure_reasons must be a list of str"
            )

        completed_at = cls._parse_dt(data["completed_at"], "completed_at")

        return TurnRecord(
            task_id=task_id,
            goal=goal,
            final_answer=final_answer,
            status=status,
            planned_actions=tuple(planned_actions_raw),
            memory_degraded=memory_degraded,
            memory_write_failed=memory_write_failed,
            disclosure_reasons=tuple(disclosure_reasons_raw),
            completed_at=completed_at,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_canonical_uuid(
        value: object, field_name: str = "session_id"
    ) -> str:
        if not isinstance(value, str):
            raise SessionDataCorruptionError(
                f"{field_name} must be str, got {type(value).__name__}"
            )
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise SessionDataCorruptionError(
                f"{field_name} is not a valid UUID: {value!r}"
            ) from exc

    @staticmethod
    def _require_aware(value: object, field_name: str = "") -> datetime:
        """isinstance(datetime) BEFORE .tzinfo — per spec."""
        if not isinstance(value, datetime):
            raise SessionDataCorruptionError(
                f"{field_name} must be datetime, got {type(value).__name__}"
            )
        if value.tzinfo is None:
            raise SessionDataCorruptionError(
                f"{field_name} must be timezone-aware (got naive datetime)"
            )
        return value

    @staticmethod
    def _parse_dt(value: object, field_name: str = "") -> datetime:
        """Parse ISO string to timezone-aware datetime. Naive strings are rejected."""
        if not isinstance(value, str):
            raise SessionDataCorruptionError(
                f"{field_name} must be a str (ISO datetime), got {type(value).__name__}"
            )
        try:
            dt = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SessionDataCorruptionError(
                f"{field_name} is not a valid ISO datetime: {value!r}"
            ) from exc
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise SessionDataCorruptionError(
                f"{field_name} must be timezone-aware (got naive datetime string: {value!r})"
            )
        return dt

    @staticmethod
    def _validate_invariants(session: SessionState) -> None:
        if session.updated_at < session.created_at:
            raise SessionDataCorruptionError(
                f"updated_at ({session.updated_at.isoformat()}) must be >= "
                f"created_at ({session.created_at.isoformat()})"
            )
        if session.turns:
            last_completed_at = session.turns[-1].completed_at
            if session.updated_at != last_completed_at:
                raise SessionDataCorruptionError(
                    f"updated_at ({session.updated_at.isoformat()}) must equal "
                    f"turns[-1].completed_at ({last_completed_at.isoformat()})"
                )
