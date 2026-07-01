from __future__ import annotations

import dataclasses
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from agent_core.conversation.llm_responder import LLMResponderRequest, TextLLMResponder
from agent_core.conversation.models import ConversationRoute
from agent_core.conversation.pending_state import PendingConversationState
from agent_core.conversation.profile_memory import (
    PROFILE_CANCEL,
    PROFILE_CONFIRM,
    PendingProfileConfirmationState,
    ProfileFactCandidate,
    answer_profile_query,
    build_confirmation_prompt,
    detect_profile_fact_candidate,
    detect_profile_query,
    save_confirmed_profile_fact,
)
from agent_core.conversation.response_composer import ResponseComposer
from agent_core.conversation.router import ConversationRouter
from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.memory_agent import MemoryAgent
from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intents import IntentName
from agent_core.planning.slot_validator import SlotValidator
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, ToolName
from agent_core.state.session_state import SessionState, SessionStatusView, TurnRecord

# CONV-P0 P0-3: conversation trace meanings recorded on state.history for direct/
# clarification turns (prefix keeps them distinct from runtime plan/step history lines).
_CONV_TRACE_PREFIX = "conv:"
_CONV_DIRECT_ROUTES = (ConversationRoute.DIRECT_RESPONSE, ConversationRoute.CLARIFICATION)

if TYPE_CHECKING:
    from agent_core.confirmation.models import ConfirmedSaveOperation
    from agent_core.session_persistence.base import SessionStoreProtocol

# Real recall (CLI) enables the bounded same-tick FTS stabilization (SPEC_M7B §10): at most
# 5 attempts, stop on first hit, never retry a remote failure. Tests override this.
_RECALL_MAX_ATTEMPTS = 5

# CONV-P0 P0-6B: pending state helpers — narrow patterns, intentionally minimal.
_PENDING_CANCEL = re.compile(
    r'^(?:hủy|bỏ\s+qua|không|thôi|cancel)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_PENDING_AMBIGUOUS_ACK = re.compile(
    r'^(?:ok|okay|có|ừ|ừm|vâng|được)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
# Intents whose presence (with no missing slots) means the user has issued a new
# complete command — clear pending and fall through to normal routing.
_CLEAR_PENDING_ON_COMPLETE_INTENT = frozenset({
    IntentName.CALCULATE,
    IntentName.CALCULATE_THEN_SAVE_NOTE,
    IntentName.READ_NOTE,
    IntentName.READ_NOTE_THEN_SUMMARIZE,
    IntentName.WRITE_NOTE,
    IntentName.WEB_SEARCH,
    IntentName.WEB_SEARCH_THEN_SAVE_NOTE,
    IntentName.PROJECT_CONTEXT_QUERY,
})


class SessionRuntime:
    """Manages a multi-turn session over a shared store.

    Precondition: agent + store must come from the same composition root (QĐ-2).
    SessionRuntime does NOT enforce this via reflection — caller's responsibility.

    Persistence contract:
      - Without session_store: turns accumulate in-memory only (SR1/SR2 behaviour).
      - With session_store: caller MUST pass an explicit session object.
        Violation → ValueError (programming error, caught at startup, not at runtime).
      - handle_turn persists a candidate session BEFORE mutating the live session.
        If save() raises, the live session is NOT mutated (fail-closed for history).
    """

    def __init__(
        self,
        agent: RuntimeAgent,
        store: MemoryStoreProtocol,
        *,
        session: SessionState | None = None,
        session_store: SessionStoreProtocol | None = None,
        user_id: str | None = None,
        conversation_router: ConversationRouter | None = None,
        llm_responder: TextLLMResponder | None = None,
    ) -> None:
        if session is None and session_store is not None:
            raise ValueError(
                "session_store requires an explicit session object. "
                "Pass session= when constructing SessionRuntime with a store."
            )
        # Application-owned identity for M7-A confirmed saves. Optional (defaults None) so
        # existing natural-language callers stay compatible; blank non-None is rejected.
        if user_id is not None:
            if not isinstance(user_id, str) or not user_id.strip():
                raise ValueError("user_id must be None or a nonblank string")
            user_id = user_id.strip()
        self._user_id = user_id
        self._agent = agent
        self._store = store
        self._session_store = session_store
        # CONV-P0 P0-3: conversation layer at the handle_turn seam (default minimal router).
        self._conversation_router = conversation_router or ConversationRouter()
        self._response_composer = ResponseComposer()
        self._llm_responder = llm_responder
        # CONV-P0 P0-6B: short-term pending state for note slot continuation (session-local).
        self._pending_conversation_state: PendingConversationState | None = None
        # CONV-P0 P0-7B: short-term pending state for profile fact confirmation (session-local).
        self._pending_profile_confirmation: PendingProfileConfirmationState | None = None
        if session is not None:
            self._session = session
        else:
            now = datetime.now(timezone.utc)
            self._session = SessionState(
                session_id=str(uuid4()),
                created_at=now,
                updated_at=now,
            )

    @property
    def session_id(self) -> str:
        return self._session.session_id

    def handle_turn(self, user_message: str) -> AgentState:
        state = AgentState(
            goal=user_message,
            memory=self._store,
            session_id=self._session.session_id,
        )

        # CONV-P0 P0-7B priority 1: profile fact confirmation pending.
        if self._pending_profile_confirmation is not None:
            result = self._try_handle_profile_confirmation(user_message, state)
            if result is not None:
                return result
            state = AgentState(
                goal=user_message,
                memory=self._store,
                session_id=self._session.session_id,
            )

        # CONV-P0 P0-6B priority 2: pending note slot continuation.
        if self._pending_conversation_state is not None:
            pending_result = self._try_handle_pending(user_message, state)
            if pending_result is not None:
                return pending_result
            # None → pending cleared; fall through to normal routing with a fresh state.
            state = AgentState(
                goal=user_message,
                memory=self._store,
                session_id=self._session.session_id,
            )

        # CONV-P0 P0-7B priority 3: profile query — answer from confirmed facts before router.
        profile_answer = self._maybe_answer_profile_query(user_message, state)
        if profile_answer is not None:
            return profile_answer

        # CONV-P0 P0-7B priority 4: profile fact candidate — ask confirmation.
        profile_pending = self._maybe_start_profile_confirmation(user_message, state)
        if profile_pending is not None:
            return profile_pending

        # CONV-P0 P0-3 seam: classify before runtime. Direct/clarification routes complete
        # the state here WITHOUT planner/tool/memory; everything else falls through to run().
        route_result = self._conversation_router.route(state)
        if route_result.route in _CONV_DIRECT_ROUTES:
            for meaning in route_result.trace:
                state.history.append(_CONV_TRACE_PREFIX + meaning.value)
            state.complete(route_result.response_text or "")
            state.history.append(_CONV_TRACE_PREFIX + "state_finalized")
            self._record_terminal_state(state)      # reuse SR2/SR3 persist-before-mutate
            return state

        if route_result.route is ConversationRoute.LLM_RESPONSE:
            for meaning in route_result.trace:
                state.history.append(_CONV_TRACE_PREFIX + meaning.value)

            if self._llm_responder is None:
                state.history.append(_CONV_TRACE_PREFIX + "llm_response_unconfigured")
                state.complete(self._response_composer.compose_llm_unconfigured())
            else:
                state.history.append(_CONV_TRACE_PREFIX + "llm_response_requested")
                try:
                    result = self._llm_responder.generate(
                        LLMResponderRequest(
                            user_text=state.goal,
                            intent=route_result.intent,
                            route=route_result.route.value,
                            session_id=state.session_id,
                            task_id=state.task_id,
                        )
                    )
                    answer = result.text.strip()
                    if not answer:
                        raise ValueError("empty LLMResponder text")
                    state.history.append(_CONV_TRACE_PREFIX + "llm_response_generated")
                    state.complete(answer)
                except Exception as exc:
                    state.errors.append(f"llm_response:{type(exc).__name__}")
                    state.history.append(_CONV_TRACE_PREFIX + "llm_response_failed")
                    state.complete(self._response_composer.compose_llm_failed())

            state.history.append(_CONV_TRACE_PREFIX + "state_finalized")
            self._record_terminal_state(state)
            return state

        state = self._agent.run(state)              # raise → không tới append (QĐ-SR2-E case 2)
        if not state.is_terminal():                 # bug-guard (QĐ-SR2-E case 3)
            raise RuntimeError(
                f"run() returned non-terminal state: {state.status}"
            )
        self._record_terminal_state(state)          # SR2/SR3 persist-before-mutate
        # CONV-P0 P0-6B: after runtime, detect write_note clarification → set pending.
        self._maybe_capture_pending(user_message, state)
        return state

    def run_confirmed_decision_save(
        self,
        operation: "ConfirmedSaveOperation",
    ) -> AgentState:
        """M7-A dedicated structured save run (SPEC §15.2). Not a natural-language turn.

        Builds a run-only AgentState carrying the frozen operation and delegates the
        required write to ``RuntimeAgent.run_confirmed_save``. Identity is application-owned;
        it is never recovered from decision text, evidence metadata or a hidden client default.
        """
        if not self._user_id:
            raise ValueError(
                "run_confirmed_decision_save requires an application-owned user_id"
            )
        session_id = self._session.session_id
        if (
            operation.session_id is None
            or not operation.session_id.strip()
            or operation.session_id != session_id
        ):
            raise ValueError(
                "operation session_id must be nonblank and equal the current session id"
            )

        state = AgentState(
            goal="Persist confirmed project decision",
            task_id=operation.task_id,
            user_id=self._user_id,
            session_id=session_id,
            memory=self._store,
            confirmed_save_operation=operation,
        )
        state = self._agent.run_confirmed_save(state)  # raise → no append (fail-closed history)
        if not state.is_terminal():
            raise RuntimeError(
                f"run_confirmed_save returned non-terminal state: {state.status}"
            )
        self._record_terminal_state(state)
        return state

    def run_memory_recall(
        self,
        query: str,
        *,
        max_attempts: int = _RECALL_MAX_ATTEMPTS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> AgentState:
        """M7-B dedicated cross-process recall run (SPEC_M7B §11). Not a natural-language turn.

        Builds a run-only AgentState for THIS session (a fresh session_id relative to the
        writing session does not block recall — retrieval is scoped by project_id + user_id,
        not session_id) and delegates to ``RuntimeAgent.run_memory_recall``. Identity is the
        application-owned ``user_id`` (same source as M7-A); it is never recovered from the
        query. The recall never reads ``confirmed_save_operation`` and never uses a local store.
        """
        if not query or not query.strip():
            raise ValueError("recall query must be a nonblank string")

        state = AgentState(
            goal=query.strip(),
            user_id=self._user_id,
            session_id=self._session.session_id,
            memory=self._store,
        )
        state = self._agent.run_memory_recall(
            state, max_attempts=max_attempts, sleep_fn=sleep_fn
        )
        if not state.is_terminal():
            raise RuntimeError(
                f"run_memory_recall returned non-terminal state: {state.status}"
            )
        self._record_terminal_state(state)
        return state

    # ------------------------------------------------------------------
    # CONV-P0 P0-7B — user profile memory
    # ------------------------------------------------------------------

    def _try_handle_profile_confirmation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """Handle turns when a profile fact confirmation is pending.

        Returns a completed AgentState if handled, or None to fall through.
        """
        pending = self._pending_profile_confirmation
        assert pending is not None
        text = user_message.strip()

        if PROFILE_CANCEL.match(text):
            self._pending_profile_confirmation = None
            state.history.append("conv:profile_confirmation_cancelled")
            state.complete("Đã hủy. Tôi sẽ không lưu thông tin này.")
            state.history.append("conv:state_finalized")
            self._record_terminal_state(state)
            return state

        if PROFILE_CONFIRM.match(text):
            self._pending_profile_confirmation = None
            state.history.append("conv:profile_confirmation_accepted")
            ok = save_confirmed_profile_fact(
                pending.candidate, self._store, state.session_id
            )
            if ok:
                state.complete("Đã lưu.")
            else:
                state.errors.append("profile_save_failed")
                state.complete("Không thể lưu thông tin. Vui lòng thử lại.")
            state.history.append("conv:state_finalized")
            self._record_terminal_state(state)
            return state

        # Clear on decisive non-profile direct/clarification routes (identity, greeting, …).
        # Mirrors P0-6B _try_handle_pending step 3 logic.
        route_result = self._conversation_router.route(state)
        if route_result.route in _CONV_DIRECT_ROUTES:
            self._pending_profile_confirmation = None
            return None

        # Clear on complete runtime commands (calc, read_note, …).
        # Mirrors P0-6B _try_handle_pending step 4 logic.
        parsed = SlotValidator().validate(RuleBasedIntentParser().parse(text))
        if parsed.intent in _CLEAR_PENDING_ON_COMPLETE_INTENT and not parsed.missing_slots:
            self._pending_profile_confirmation = None
            return None

        # Expiration
        if len(self._session.turns) - pending.created_at_turn >= pending.expires_after_turns:
            self._pending_profile_confirmation = None
            return None

        # Everything else: reprompt
        state.history.append("conv:profile_confirmation_reprompt")
        state.complete(pending.prompt_text)
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_answer_profile_query(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """Return a completed AgentState if the message is a profile query with a known answer."""
        query = detect_profile_query(user_message.strip())
        if query is None:
            return None
        answer = answer_profile_query(query, self._store)
        if answer is None:
            return None
        state.history.append("conv:profile_query_answered")
        state.complete(answer)
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_start_profile_confirmation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """Detect a profile fact candidate and start a confirmation pending if found."""
        candidate = detect_profile_fact_candidate(user_message.strip())
        if candidate is None:
            return None
        prompt = build_confirmation_prompt(candidate)
        self._pending_profile_confirmation = PendingProfileConfirmationState(
            kind="profile_fact_confirmation",
            candidate=candidate,
            prompt_text=prompt,
            session_id=self.session_id,
            created_at_turn=len(self._session.turns),
        )
        state.history.append("conv:profile_candidate_detected")
        state.complete(prompt)
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    # CONV-P0 P0-6B — pending note slot continuation
    # ------------------------------------------------------------------

    def _try_handle_pending(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """Dispatch when a pending note-name clarification is active.

        Returns a completed AgentState if the pending interaction was fully
        handled, or None to fall through to normal routing (pending cleared).
        """
        pending = self._pending_conversation_state
        assert pending is not None
        text = user_message.strip()

        # 1. Cancel → clear pending, return safe cancellation.
        if _PENDING_CANCEL.match(text):
            self._pending_conversation_state = None
            state.history.append("conv:pending_note_cancelled")
            state.complete("Đã hủy yêu cầu ghi chú. Tôi chưa lưu gì cả.")
            state.history.append("conv:state_finalized")
            self._record_terminal_state(state)
            return state

        # 2. Ambiguous ack (ok, có, ừ, …) → reprompt without writing.
        # Must run BEFORE route classification: the router may classify "ok" as
        # DIRECT_RESPONSE (a greeting/affirmation), which would incorrectly clear pending.
        if _PENDING_AMBIGUOUS_ACK.match(text):
            state.history.append("conv:pending_note_reprompt")
            prompt = pending.prompt_text or "Bạn muốn dùng tên ghi chú là gì?"
            state.complete(prompt)
            state.history.append("conv:state_finalized")
            self._record_terminal_state(state)
            return state

        # 3. High-confidence direct/clarification route (identity, greeting, …) → clear.
        route_result = self._conversation_router.route(state)
        if route_result.route in _CONV_DIRECT_ROUTES:
            self._pending_conversation_state = None
            return None  # fall through; normal routing handles the response

        # 4. Complete runtime command (full write_note, calc, read_note, …) → clear.
        parsed = SlotValidator().validate(RuleBasedIntentParser().parse(text))
        if parsed.intent in _CLEAR_PENDING_ON_COMPLETE_INTENT and not parsed.missing_slots:
            self._pending_conversation_state = None
            return None

        # 5. Profile query — clear note pending and fall through to profile query handler.
        if detect_profile_query(text) is not None:
            self._pending_conversation_state = None
            return None

        # 6. Expiration check — expire after `expires_after_turns` unresolved turns.
        if len(self._session.turns) - pending.created_at_turn >= pending.expires_after_turns:
            self._pending_conversation_state = None
            return None

        # 7. Treat remaining input as the note_name slot answer.
        return self._resume_write_note(pending, note_name=text, state=state)

    def _resume_write_note(
        self,
        pending: PendingConversationState,
        note_name: str,
        state: AgentState,
    ) -> AgentState:
        """Complete the write_note flow with the now-known note_name."""
        self._pending_conversation_state = None
        content = pending.collected_slots.get("content", "")
        state.history.append("conv:pending_note_name_resolved")
        try:
            mem_agent = MemoryAgent(
                self._store,
                user_id=None,
                session_id=state.session_id,
            )
            mem_agent.write_note(name=note_name, content=content, task_id=state.task_id)
            state.complete(f'Đã lưu ghi chú "{note_name}": {content}.')
        except Exception as exc:
            state.errors.append(f"pending_write_note:{type(exc).__name__}")
            state.complete(f'Không thể lưu ghi chú "{note_name}". Vui lòng thử lại.')
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_capture_pending(self, user_message: str, state: AgentState) -> None:
        """After a runtime run, detect write_note clarification and store pending state.

        Captures only when: WRITE_NOTE intent, note_name is missing, content is known,
        and the plan was a single FINISH step (clarification plan shape).
        """
        if state.status != AgentStatus.COMPLETED:
            return
        if len(state.plan) != 1 or state.plan[0].action != ToolName.FINISH:
            return
        parsed = SlotValidator().validate(RuleBasedIntentParser().parse(user_message))
        if parsed.intent is not IntentName.WRITE_NOTE:
            return
        if "note_name" not in parsed.missing_slots:
            return
        if not parsed.content:
            return
        self._pending_conversation_state = PendingConversationState(
            kind="write_note_missing_note_name",
            intent=parsed.intent.value,
            original_goal=user_message,
            missing_slots=("note_name",),
            collected_slots={"content": str(parsed.content)},
            prompt_text=state.final_answer or "",
            source_route="RUNTIME_FALLBACK",
            session_id=self.session_id,
            created_at_turn=len(self._session.turns),
        )

    def _record_terminal_state(self, state: AgentState) -> None:
        """Build a TurnRecord and persist-before-mutate. Shared by NL and confirmed-save paths.

        FAILED → final_answer masked to None (anti-leak, QĐ-SR2-C). The confirmed operation,
        evidence object, decision content and request payload are never serialized as fields.
        """
        record = TurnRecord(
            task_id=state.task_id,
            goal=state.goal,
            final_answer=(
                state.final_answer if state.status == AgentStatus.COMPLETED else None
            ),
            status=state.status,
            planned_actions=tuple(s.action.value for s in state.plan),
            memory_degraded=state.memory_degraded,
            memory_write_failed=state.memory_write_failed,
            disclosure_reasons=tuple(state.disclosure_reasons),
            completed_at=datetime.now(timezone.utc),
        )

        if self._session_store is not None:
            # Build candidate WITHOUT mutating live session (persist-before-mutate)
            candidate = dataclasses.replace(
                self._session,
                turns=self._session.turns + [record],
                updated_at=record.completed_at,
            )
            self._session_store.save(candidate)  # SessionPersistenceError → propagate

        self._session.append_turn(record)          # only after successful save

    def get_status(self) -> SessionStatusView:
        return self._session.status_view()

    def get_history(self, *, limit: int = 10) -> tuple[TurnRecord, ...]:
        return self._session.history_view(limit)
