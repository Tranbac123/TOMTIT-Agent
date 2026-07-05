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
    AutoProfileCandidate,
    BlockedProfileAttempt,
    PendingProfileConfirmationState,
    ProfileFactCandidate,
    ProfileQuery,
    answer_profile_query,
    answer_yes_no_memory_query,
    build_affection_explanation_response,
    build_affection_memory_ack,
    build_affection_relation_response,
    build_auto_ack_message,
    build_blocked_value_response,
    build_confirmation_prompt,
    build_external_affection_ack,
    build_followup_response,
    build_name_update_ack,
    build_near_miss_response,
    build_negation_no_affection_response,
    build_negative_desire_response,
    build_negative_preference_ack,
    build_negative_skill_ack,
    build_occ_correction_ack,
    build_occupation_removal_ack,
    build_one_sided_affection_response,
    build_person_affinity_response,
    build_delete_all_confirmation_prompt,
    build_delete_all_done,
    build_profile_conflict_message,
    build_profile_fact_ack,
    build_relation_removal_ack,
    build_relationship_typo_clarification,
    build_repair_clarification,
    build_relation_removal_not_found,
    build_relation_update_ack,
    build_unrelated_external_affection_response,
    collect_profile_snapshot,
    delete_occupation_fact,
    delete_relation_fact,
    detect_auto_profile_candidate,
    detect_blocked_auto_profile_value,
    detect_correction_remainder,
    detect_occupation_name_correction,
    detect_occupation_removal,
    detect_profile_fact_candidate,
    detect_profile_query,
    delete_all_profile_memory,
    detect_delete_all_confirmation,
    detect_delete_all_memory_request,
    detect_reminder_inner_clause,
    detect_repair_intent,
    detect_relation_alias_query,
    detect_relation_removal_cmd,
    detect_relation_update_cmd,
    detect_relationship_typo,
    detect_self_name_phrase_update,
    detect_self_name_update,
    find_existing_profile_value,
    looks_like_proper_full_name,
    resolve_preference_conflicts,
    resolve_skill_conflicts,
    save_affection_fact,
    save_comparative_fact,
    save_favorite_fact,
    save_auto_profile_fact,
    save_confirmed_profile_fact,
    save_external_affection_fact,
    save_relation_update,
    save_self_name_update,
)
from agent_core.conversation.memory_operations import (
    apply_memory_operation,
    apply_memory_operations,
    goal_already_active,
    parse_memory_operation,
)
from agent_core.conversation.semantic_extractor import (
    MIN_EXTRACTION_CONFIDENCE,
    RuleBasedSemanticOperationExtractor,
    SemanticExtractionRequest,
    SemanticOperationExtractorProtocol,
    detect_unsupported_memory_domain,
)
from agent_core.conversation.profile_semantics import (
    SemanticProfileIntent,
    classify_profile_semantic_intent,
)
from agent_core.conversation.simple_comparison import try_answer_comparison
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

# P0-7G: object words that mean "the user" in an external affection statement ("Quý thích tôi").
_EXTERNAL_AFFECTION_SELF_WORDS = frozenset({"tôi", "mình", "tao", "ta"})

# P0-7G-FIX4B: loose pattern for exact saved-name fallback (object captured as .+? instead of
# the bounded \S+(?:\s+\S+)? used in profile_semantics). Only used when saved self-name has
# 3+ tokens; an exact norm comparison prevents overmatch on long non-name phrases.
_RE_EXTERNAL_AFFECTION_LOOSE = re.compile(
    r'^(\S+)\s+(?:thích|yêu|thương|crush|quý\s+mến)\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE,
)

if TYPE_CHECKING:
    from agent_core.confirmation.models import ConfirmedSaveOperation
    from agent_core.session_persistence.base import SessionStoreProtocol

# Real recall (CLI) enables the bounded same-tick FTS stabilization (SPEC_M7B §10): at most
# 5 attempts, stop on first hit, never retry a remote failure. Tests override this.
_RECALL_MAX_ATTEMPTS = 5

# CONV-P0 P0-7E: minimal current-session recall. Answers "what did I just ask/say" from
# session-local history only — no memory write, no long-term recall, no cross-session claim.
_SESSION_RECALL_Q = re.compile(
    r'^(?:'
    r'(?:tôi|mình)\s+vừa\s+hỏi\s+(?:gì\s+)?(?:bạn)?'
    r'|câu\s+(?:hỏi\s+)?trước\s+(?:tôi|mình)\s+hỏi\s+gì'
    r'|(?:tôi|mình)\s+vừa\s+nói\s+gì'
    r')\s*[?？]?\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7F-FIX3 Part H: unsupported current-info (weather / date / time). This runtime
# has no weather or clock tool, so these requests get a deterministic "not supported" reply
# instead of the generic planner fallback. The common typo "thời thiết" is normalized to
# "thời tiết" before matching.
_RE_UNSUPPORTED_CURRENT_INFO = re.compile(
    r'(?:'
    r'thời\s+tiết'                                  # weather (post-typo-normalization)
    r'|hôm\s+nay\s+(?:là\s+)?ngày\s+(?:bao\s+nhiêu|mấy)'   # "hôm nay ngày bao nhiêu/mấy"
    r'|hôm\s+nay\s+(?:là\s+)?thứ\s+mấy'             # "hôm nay thứ mấy"
    r'|ngày\s+(?:hôm\s+nay|mai|mấy)\b'
    r'|bây\s+giờ\s+là\s+mấy\s+giờ|mấy\s+giờ\s+rồi'  # clock
    r')',
    re.IGNORECASE,
)
_UNSUPPORTED_CURRENT_INFO_RESPONSE = (
    "Hiện tại trong runtime này tôi chưa hỗ trợ trả lời thời gian/ngày/thời tiết trực tiếp, "
    "nên chưa thể trả lời chính xác yêu cầu này. Tôi chưa gọi tool hay tra cứu dữ liệu nào "
    "cho việc này."
)

# CONV-P0 P0-7F-FIX4 Part E: unsupported open-knowledge Q&A ("mèo có phải là chó không?",
# "AI là gì?"). This rule-based runtime has no LLM/web lookup, so obvious open-QA questions
# get a deterministic "not supported" reply instead of the generic tool-example fallback —
# a safe seam for a future P0-8A LLMResponder. Profile queries run first (priority 4) and are
# never reached here; the definition lane is deliberately narrow (single-token subject) and
# excludes identity/self words so "tomtit là gì?" / "bạn là gì?" stay DIRECT_RESPONSE and
# multi-word prompts ("giải thích AI là gì?") keep flowing to the router.
_OPEN_QA_STOP_SUBJECTS: frozenset[str] = frozenset({
    "tôi", "mình", "bạn", "tao", "ta", "nó", "đây", "đó", "gì", "tomtit",
})
_RE_OPEN_QA_YESNO = re.compile(
    r'^\S+\s+có\s+phải\s+là\s+.+\s+(?:không|ko)\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_OPEN_QA_DEFINITION = re.compile(
    r'^([^\s?？]+)\s+là\s+g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)
_UNSUPPORTED_OPEN_QA_RESPONSE = (
    "Hiện tại trong runtime rule-based này tôi chưa hỗ trợ trả lời câu hỏi kiến thức mở. "
    "Tôi chưa gọi LLM hay tra cứu dữ liệu nào cho câu này."
)

# CONV-P0 P0-7K-FIX3: bounded continuation ("và ML nữa", "cả X nữa", "thêm X nữa").
_RE_CONTINUATION = re.compile(
    r'^(?:và|cả|thêm|còn)\s+(.+?)\s+nữa\s*[.!]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX3-FIX1: explicit cancel for a pending delete-all confirmation.
_RE_DELETE_CANCEL = re.compile(
    r'^(?:không|khong|ko|hủy|huỷ|thôi|bỏ\s+qua|cancel|no)\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX4 C: current-state skill update ("bây giờ tôi biết hát và đọc sách").
# Strips a leading temporal marker so the remainder re-runs through the skill pipeline.
_RE_CURRENT_STATE_SKILL = re.compile(
    r'^(?:bây\s+giờ|hiện\s+tại|giờ|từ\s+nay)\s*,?\s+'
    r'((?:tôi|mình)\s+(?:không\s+)?biết\b.+)$',
    re.IGNORECASE,
)

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
        semantic_extractor: SemanticOperationExtractorProtocol | None = None,
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
        # CONV-P0 P0-7K: hybrid semantic memory extractor. Injectable (tests use the
        # fake fixture extractor); the default is the deterministic rule-based backend —
        # provider-free, no LLM/network. An LLM adapter would slot in behind the same
        # protocol and can only PROPOSE operations; every write still passes validation.
        self._semantic_extractor = semantic_extractor or RuleBasedSemanticOperationExtractor()
        # CONV-P0 P0-6B: short-term pending state for note slot continuation (session-local).
        self._pending_conversation_state: PendingConversationState | None = None
        # CONV-P0 P0-7B: short-term pending state for profile fact confirmation (session-local).
        self._pending_profile_confirmation: PendingProfileConfirmationState | None = None
        # CONV-P0 P0-7C: count of profile facts confirmed in this session. Used to gate
        # profile_summary store reads — avoids reading store for sessions with no profile facts,
        # which preserves the zero-side-effect guarantee for the "bạn biết gì về tôi?" route
        # when no facts have been saved.
        self._confirmed_profile_fact_count: int = 0
        # CONV-P0 P0-7F: session-local turn index of the last answered profile query,
        # used only for the "gì nữa?" follow-up. Never persisted to memory.
        self._profile_query_context_turn: int | None = None
        # CONV-P0 P0-7K-FIX1: kind of the last answered profile query, for the bounded
        # goal follow-up ("và gì nữa?"). Session-local only, never persisted.
        self._last_profile_query_kind: str | None = None
        # CONV-P0 P0-7K-FIX3: bounded continuation context ("và ML nữa") + delete-all
        # pending confirmation. Session-local only, never persisted.
        self._last_memory_write_kind: str | None = None
        self._pending_delete_all: bool = False
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

        # CONV-P0 P0-7K-FIX3 priority 0.5: delete-all memory pending confirmation.
        if self._pending_delete_all:
            delete_result = self._handle_delete_all_pending(user_message, state)
            if delete_result is not None:
                return delete_result
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

        # CONV-P0 P0-7K-FIX3 priority 1.5: delete-all memory request → set pending, confirm.
        delete_req = self._maybe_handle_delete_all_request(user_message, state)
        if delete_req is not None:
            return delete_req

        # CONV-P0 P0-7K-FIX3-FIX1 priority 1.55: a stray delete confirmation with no
        # pending request must not delete or claim success.
        stray_confirm = self._maybe_handle_stray_delete_confirmation(user_message, state)
        if stray_confirm is not None:
            return stray_confirm

        # CONV-P0 P0-7K-FIX3 priority 1.6: reminder/correction with an inner memory clause
        # → re-dispatch the inner clause; standalone repair → clarification. Prevents the
        # raw reminder sentence from being saved as memory.
        reminder = self._maybe_handle_reminder_or_repair(user_message, state)
        if reminder is not None:
            return reminder

        # CONV-P0 P0-7K-FIX3 priority 1.7: multi-query memory message ("Q1?\nQ2?").
        multi = self._maybe_handle_multi_query(user_message, state)
        if multi is not None:
            return multi

        # CONV-P0 P0-7K-FIX3 priority 1.8: bounded continuation ("và ML nữa") using the
        # last successful memory-write context.
        continuation = self._maybe_handle_continuation(user_message, state)
        if continuation is not None:
            return continuation

        # CONV-P0 P0-7K-FIX4 priority 1.85: current-state skill update
        # ("bây giờ tôi biết hát và đọc sách") — strip the marker, re-dispatch the skill
        # clause (positive skills supersede prior negatives).
        cs_skill = self._maybe_handle_current_state_skill(user_message, state)
        if cs_skill is not None:
            return cs_skill

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

        # CONV-P0 P0-7E priority 3: minimal current-session recall ("tôi vừa hỏi gì?").
        # Answered before profile/router so it is not swallowed by the generic fallback.
        recall = self._maybe_answer_session_recall(user_message, state)
        if recall is not None:
            return recall

        # CONV-P0 P0-7F priority 3.5: safe numeric comparison ("1 > 2", "2 == 2").
        # Runs before the arithmetic calculator so equality is not misrouted to a numeric result.
        comparison = self._maybe_answer_comparison(user_message, state)
        if comparison is not None:
            return comparison

        # CONV-P0 P0-7K priority 3.9: unsupported/future memory domains (schedule,
        # historical query, assistant nickname) — classified honestly, never written,
        # so they cannot corrupt profile memory. Schedule → P0-7L, history → P0-7M,
        # nickname → P0-7N.
        unsupported = self._maybe_answer_unsupported_memory_domain(user_message, state)
        if unsupported is not None:
            return unsupported

        # CONV-P0 P0-7B priority 4: profile query — answer from confirmed facts before router.
        profile_answer = self._maybe_answer_profile_query(user_message, state)
        if profile_answer is not None:
            return profile_answer

        # CONV-P0 P0-7I priority 4.1: correction lead-in stripping ("không, ", "ý tôi là ",
        # "tôi mới/vừa nói ... mà") — re-dispatches the remainder through the normal write
        # detectors so a correction is understood instead of falling to a generic fallback.
        correction = self._maybe_handle_correction(user_message, state)
        if correction is not None:
            return correction

        # CONV-P0 P0-7K-FIX1 priority 4.05: low-confidence relationship typo
        # ("bạn ái của tôi là quý") — ask for confirmation, never write (fail-safe).
        typo = self._maybe_clarify_relationship_typo(user_message, state)
        if typo is not None:
            return typo

        # CONV-P0 P0-7K priority 4.11: hybrid semantic extraction — complex/multi-fact/
        # correction utterances route through the semantic extractor, which PROPOSES
        # MemoryOperation[]; every operation passes policy validation and conflict
        # resolution before any write. Simple utterances stay deterministic.
        extraction = self._maybe_handle_semantic_extraction(user_message, state)
        if extraction is not None:
            return extraction

        # CONV-P0 P0-7J priority 4.12: Memory Kernel v1 — structured update semantics
        # (occupation stop "không làm X nữa", affection removal, relationship
        # current-update "bây giờ người yêu...", goal add/switch). Operations that do
        # not apply to current memory state fall through to the handlers below.
        memop = self._maybe_handle_memory_operation(user_message, state)
        if memop is not None:
            return memop

        # CONV-P0 P0-7I priority 4.15: occupation removal ("tôi không phải nông dân").
        occ_removed = self._maybe_handle_occupation_removal(user_message, state)
        if occ_removed is not None:
            return occ_removed

        # CONV-P0 P0-7H-FIX1 priority 4.2: occupation/name correction
        # ("không tôi làm nông là nông dân chứ không phải tên tôi là nông dân").
        occ_corr = self._maybe_handle_occupation_correction(user_message, state)
        if occ_corr is not None:
            return occ_corr

        # CONV-P0 P0-7H priority 4.3: explicit relation update/removal commands
        # ("sửa bạn gái của tôi thành May", "cập nhật Quý không phải là bạn gái của tôi").
        # Must run before P4.5 and before P7 (auto-save rejects the "sửa"/"cập nhật" prefix).
        rel_cmd = self._maybe_handle_relation_cmd(user_message, state)
        if rel_cmd is not None:
            return rel_cmd

        # CONV-P0 P0-7F priority 4.5: semantic profile layer — skill/occupation/preference
        # split/person-affinity/muốn desires/relationship variants + yes-no + "gì nữa" follow-up.
        semantic = self._maybe_handle_semantic_profile(user_message, state)
        if semantic is not None:
            return semantic

        # CONV-P0 P0-7G-FIX4B priority 4.6: exact saved-name external affection fallback.
        # Handles "Quý thích Nguyễn Văn Bắc" (3+ token name) when profile_semantics
        # bounded regex (\S+(?:\s+\S+)?) cannot capture the full object. Only activates
        # when the current saved self-name has 3+ tokens; uses exact-norm comparison to
        # prevent overmatch on long non-name phrases like "giải thích cho tôi về AI".
        ext_aff_exact = self._maybe_handle_exact_name_external_affection(user_message, state)
        if ext_aff_exact is not None:
            return ext_aff_exact

        # CONV-P0 P0-7G priority 4.8: explicit/implicit self-name update — supersede the
        # stored name ("sửa tên tôi thành ...", "tôi là <full name>" when a name exists).
        name_updated = self._maybe_update_name(user_message, state)
        if name_updated is not None:
            return name_updated

        # CONV-P0 P0-7E priority 5: direct self.name / relation.name — AUTO_SAFE save
        # (conflict-safe: never silently overwrites an existing value).
        name_saved = self._maybe_auto_save_name_relation(user_message, state)
        if name_saved is not None:
            return name_saved

        # CONV-P0 P0-7E priority 6: auto-profile claim carrying an unsafe/sensitive value —
        # specific safety response instead of a silent block + generic fallback.
        blocked = self._maybe_blocked_value_response(user_message, state)
        if blocked is not None:
            return blocked

        # CONV-P0 P0-7D priority 7: auto-save low-risk self-profile facts without confirmation.
        auto_saved = self._maybe_auto_save_profile_fact(user_message, state)
        if auto_saved is not None:
            return auto_saved

        # CONV-P0 P0-7F-FIX3 priority 9.5: deterministic "unsupported current-info"
        # (weather/date/time) reply — preempts the generic planner fallback. No tool call.
        current_info = self._maybe_answer_unsupported_current_info(user_message, state)
        if current_info is not None:
            return current_info

        # CONV-P0 P0-7F-FIX4 priority 9.6: deterministic "unsupported open-knowledge Q&A"
        # reply — preempts the generic planner fallback for obvious factual questions. No tool.
        open_qa = self._maybe_answer_unsupported_open_qa(user_message, state)
        if open_qa is not None:
            return open_qa

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
                self._confirmed_profile_fact_count += 1
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
        """Return a completed AgentState if the message is a profile query with a known answer.

        For profile_summary queries: skip store read entirely when no facts have been
        confirmed this session. This preserves the zero-side-effect contract for sessions
        with no profile data (the router's CLARIFICATION response handles those turns).
        """
        # P0-7H-FIX1 Part B: alias relation query ("bạn gái của Bắc là ai?" where Bắc = saved name)
        alias_q = detect_relation_alias_query(user_message.strip())
        if alias_q is not None:
            rel_label, name_in_query = alias_q
            current_name = collect_profile_snapshot(self._store).name
            if current_name and self._norm(name_in_query) == self._norm(current_name):
                synthetic_query = ProfileQuery(kind="relation_name", relation_label=rel_label)
                answer = answer_profile_query(synthetic_query, self._store)
                if answer is not None:
                    self._profile_query_context_turn = len(self._session.turns)
                    state.history.append("conv:profile_query_answered")
                    state.complete(answer)
                    state.history.append("conv:state_finalized")
                    self._record_terminal_state(state)
                    return state

        query = detect_profile_query(user_message.strip())
        if query is None:
            return None
        # P0-7C: profile_summary reads store; gate it on session-local fact count to avoid
        # store reads when no facts were ever saved in this session.
        if query.kind == "profile_summary" and self._confirmed_profile_fact_count == 0:
            return None
        # P0-7K-FIX1 H: the goal follow-up ("và gì nữa?") only fires immediately after a
        # goal query — otherwise the bare "và gì nữa?" is ambiguous and falls through.
        if query.kind == "goal_followup":
            if self._last_profile_query_kind not in ("self_current_goal", "self_goal", "goal_followup"):
                return None
        answer = answer_profile_query(query, self._store)
        if answer is None:
            return None
        # P0-7F: remember that a profile query was just answered, for a "gì nữa?" follow-up.
        self._profile_query_context_turn = len(self._session.turns)
        self._last_profile_query_kind = query.kind
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

    def _maybe_auto_save_profile_fact(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """AUTO_SAFE write: save low-risk self-profile facts without user confirmation.

        Fires only when: occupation/preference/goal/learning_focus candidate detected,
        no question mark, no note/command prefix. Never fires for relation.name (those
        still require explicit confirmation via _maybe_start_profile_confirmation).
        """
        candidate = detect_auto_profile_candidate(user_message.strip())
        if candidate is None:
            return None
        # P0-7I: a new positive preference supersedes a conflicting active dislike for
        # the same object (memory conflict resolution).
        if candidate.relation == "preference":
            resolve_preference_conflicts(candidate.value, "preference", self._store)
        ok = save_auto_profile_fact(candidate, self._store, state.session_id)
        if not ok:
            return None
        self._confirmed_profile_fact_count += 1
        ack = build_auto_ack_message(candidate)
        state.history.append("conv:auto_profile_saved")
        state.complete(ack)
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_answer_session_recall(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7E: answer "tôi vừa hỏi gì bạn?" from session-local history only.

        Uses the previous user turn recorded in this session. Never writes memory, never
        reads long-term memory, never claims cross-session recall. The current turn is not
        yet recorded when this runs, so ``self._session.turns`` holds only prior turns.
        """
        if not _SESSION_RECALL_Q.match(user_message.strip()):
            return None
        prev_goal = self._session.turns[-1].goal if self._session.turns else None
        state.history.append("conv:session_recall_answered")
        if prev_goal:
            state.complete(f'Bạn vừa hỏi: "{prev_goal}".')
        else:
            state.complete("Mình chưa có câu hỏi trước đó trong phiên này.")
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_auto_save_name_relation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7E: AUTO_SAFE save for direct self.name / relation.name claims.

        First-time claim → auto-save + natural ack. A claim conflicting with an existing
        stored value → deterministic guidance, never a silent overwrite (correction/delete
        remains a future phase). Unsafe/sensitive name values are rejected before saving.
        """
        candidate = detect_profile_fact_candidate(user_message.strip())
        if candidate is None:
            return None
        # Guardrail: never auto-save an unsafe/sensitive value as a name.
        from agent_core.conversation.profile_memory import _is_unsafe_or_sensitive_auto_value
        if _is_unsafe_or_sensitive_auto_value(candidate.value):
            return None

        existing = find_existing_profile_value(candidate, self._store)
        if existing is not None:
            state.history.append("conv:profile_name_conflict")
            state.complete(build_profile_conflict_message(candidate, existing))
            state.history.append("conv:state_finalized")
            self._record_terminal_state(state)
            return state

        ok = save_confirmed_profile_fact(
            candidate, self._store, state.session_id, confirmation_source="auto_safe"
        )
        if not ok:
            state.errors.append("profile_save_failed")
            state.history.append("conv:profile_autosave_failed")
            state.complete("Không thể lưu thông tin. Vui lòng thử lại.")
            state.history.append("conv:state_finalized")
            self._record_terminal_state(state)
            return state

        self._confirmed_profile_fact_count += 1
        state.history.append("conv:auto_profile_name_saved")
        state.complete(build_profile_fact_ack(candidate))
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_update_name(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7G: update the stored self-name (explicit command or full-name assertion).

        Explicit "sửa/đổi tên tôi thành X" always updates (saving first if none exists).
        Implicit "tôi là <full name>" updates ONLY when a name already exists and the new
        value differs — a first-time "tôi là X" is a fresh save handled downstream.
        """
        text = user_message.strip()
        current = collect_profile_snapshot(self._store).name

        new_name = detect_self_name_update(text)
        if new_name is None:
            phrase = detect_self_name_phrase_update(text)
            # Implicit update requires an existing name that differs from the new phrase.
            if (
                phrase is not None
                and current is not None
                and self._norm(current) != self._norm(phrase)
            ):
                new_name = phrase
            # P0-7G-FIX3 A2: first-time MULTI-WORD Title-Case full name ("tôi là Bắc Trần")
            # — a fresh save. Single-word "tôi là Bắc" stays with the priority-5 name path;
            # lowercase common-word phrases ("trai làng") are excluded by the Title-Case check.
            elif (
                phrase is not None
                and current is None
                and looks_like_proper_full_name(phrase)
            ):
                new_name = phrase
            else:
                return None

        if not save_self_name_update(new_name, self._store, state.session_id, original_text=text):
            state.errors.append("profile_save_failed")
            return self._complete_conv(
                state, "conv:profile_autosave_failed",
                "Không thể lưu thông tin. Vui lòng thử lại.",
            )
        self._confirmed_profile_fact_count += 1
        if current is None:
            return self._complete_conv(
                state, "conv:profile_name_saved", f"Đã nhớ tên bạn là {new_name}."
            )
        return self._complete_conv(
            state, "conv:profile_name_updated", build_name_update_ack(current, new_name)
        )

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _maybe_blocked_value_response(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7E: specific safety response when an auto-profile claim carries an unsafe value.

        Does not save, does not expose provenance. Only fires when the message matches an
        auto-profile pattern (so arbitrary unsupported input still falls through to router).
        """
        attempt = detect_blocked_auto_profile_value(user_message.strip())
        if attempt is None:
            return None
        state.history.append("conv:unsafe_profile_value_blocked")
        state.complete(build_blocked_value_response(attempt))
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    # ------------------------------------------------------------------
    # CONV-P0 P0-7F — semantic profile coverage + comparison
    # ------------------------------------------------------------------

    def _complete_conv(
        self, state: AgentState, marker: str, text: str
    ) -> AgentState:
        """Complete a conversation-layer turn with a trace marker (no planner/tool/memory)."""
        state.history.append(marker)
        state.complete(text)
        state.history.append("conv:state_finalized")
        self._record_terminal_state(state)
        return state

    def _maybe_answer_comparison(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7F: answer a bare numeric comparison ("1 > 2", "2 == 2") deterministically."""
        answer = try_answer_comparison(user_message)
        if answer is None:
            return None
        return self._complete_conv(state, "conv:comparison_answered", answer)

    def _maybe_answer_unsupported_current_info(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7F-FIX3 Part H: deterministic reply for weather/date/time requests.

        Normalizes the common "thời thiết" typo to "thời tiết" before matching. This runtime
        has no weather/clock tool, so the reply is honest and never fabricates a value or
        calls any tool. Only fires for clearly current-info requests; everything else falls
        through to the router.
        """
        normalized = re.sub(r"thời\s+thiết", "thời tiết", user_message.strip(), flags=re.IGNORECASE)
        if not _RE_UNSUPPORTED_CURRENT_INFO.search(normalized):
            return None
        return self._complete_conv(
            state, "conv:unsupported_current_info", _UNSUPPORTED_CURRENT_INFO_RESPONSE
        )

    def _maybe_answer_unsupported_open_qa(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7F-FIX4 Part E: deterministic reply for obvious open-knowledge questions.

        Fires only for a narrow yes/no "X có phải là Y không?" form or a single-token
        "X là gì?" definition whose subject is not an identity/self word. Profile queries and
        assistant-identity prompts are handled earlier, so they never reach this lane. Never
        saves, never calls a tool/LLM/web — a safe seam for a future P0-8A LLMResponder.
        """
        text = user_message.strip()
        if _RE_OPEN_QA_YESNO.match(text):
            return self._complete_conv(
                state, "conv:unsupported_open_qa", _UNSUPPORTED_OPEN_QA_RESPONSE
            )
        m = _RE_OPEN_QA_DEFINITION.match(text)
        if m and m.group(1).lower() not in _OPEN_QA_STOP_SUBJECTS:
            return self._complete_conv(
                state, "conv:unsupported_open_qa", _UNSUPPORTED_OPEN_QA_RESPONSE
            )
        return None

    def _has_recent_profile_query(self) -> bool:
        if self._profile_query_context_turn is None:
            return False
        return (len(self._session.turns) - self._profile_query_context_turn) <= 2

    def _semantic_to_auto_candidate(
        self, intent: SemanticProfileIntent, original_text: str
    ) -> AutoProfileCandidate | None:
        cat = intent.category
        value = intent.value or ""
        if cat == "preference.personal":
            return AutoProfileCandidate(
                relation="preference", value=value,
                original_text=original_text, preference_kind="personal",
            )
        if cat == "preference.professional":
            return AutoProfileCandidate(
                relation="preference", value=value,
                original_text=original_text, preference_kind="professional",
            )
        if cat == "skill":
            return AutoProfileCandidate(relation="skill", value=value, original_text=original_text)
        if cat == "negative_skill":
            return AutoProfileCandidate(
                relation="negative_skill", value=value, original_text=original_text
            )
        if cat == "occupation":
            return AutoProfileCandidate(relation="occupation", value=value, original_text=original_text)
        if cat == "learning_topic":
            return AutoProfileCandidate(relation="learning_focus", value=value, original_text=original_text)
        if cat == "goal":
            return AutoProfileCandidate(relation="goal", value=value, original_text=original_text)
        if cat == "household_pet":
            return AutoProfileCandidate(
                relation="household_pet", value=value, original_text=original_text
            )
        return None

    def _handle_semantic_relationship(
        self, intent: SemanticProfileIntent, user_message: str, state: AgentState
    ) -> AgentState:
        """Relationship partner-name write (reuses P0-7E name storage).

        P0-7J-FIX1 policy: an explicit self relationship assertion from the user UPDATES
        the current relationship (latest explicit fact wins) — no "sửa ..." command is
        required for common partner updates. A same-value repeat keeps the
        "vẫn đang nhớ" acknowledgement.
        """
        candidate = ProfileFactCandidate(
            subject="relation", relation="name",
            value=intent.value or "", relation_label=intent.relation_label,
            original_text=user_message.strip(),
        )
        existing = find_existing_profile_value(candidate, self._store)
        if existing is not None:
            if existing == candidate.value:
                return self._complete_conv(
                    state, "conv:profile_name_conflict",
                    build_profile_conflict_message(candidate, existing),
                )
            # P0-7G-FIX3A: the "bạn" (friend) label keeps its append + latest-wins
            # recall flow (falls through to the fresh save below).
            if candidate.relation_label != "bạn":
                label = candidate.relation_label or ""
                if not save_relation_update(
                    label, candidate.value, self._store, state.session_id,
                    original_text=user_message.strip(),
                ):
                    state.errors.append("profile_save_failed")
                    return self._complete_conv(
                        state, "conv:profile_autosave_failed",
                        "Không thể lưu thông tin. Vui lòng thử lại.",
                    )
                self._confirmed_profile_fact_count += 1
                return self._complete_conv(
                    state, "conv:relation_updated",
                    build_relation_update_ack(label, candidate.value),
                )
        ok = save_confirmed_profile_fact(
            candidate, self._store, state.session_id, confirmation_source="auto_safe"
        )
        if not ok:
            state.errors.append("profile_save_failed")
            return self._complete_conv(
                state, "conv:profile_autosave_failed",
                "Không thể lưu thông tin. Vui lòng thử lại.",
            )
        self._confirmed_profile_fact_count += 1
        return self._complete_conv(
            state, "conv:auto_profile_name_saved", build_profile_fact_ack(candidate)
        )

    def _maybe_handle_relation_cmd(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7H priority 4.3: explicit relation update/removal commands.

        "sửa bạn gái của tôi thành May" (A2) and
        "cập nhật Quý không phải là bạn gái của tôi" (A3).
        Intercepted before the auto-save gate which rejects the "sửa"/"cập nhật" prefix.
        """
        stripped = user_message.strip()

        upd = detect_relation_update_cmd(stripped)
        if upd is not None:
            label, new_name = upd
            ok = save_relation_update(
                label, new_name, self._store, state.session_id, original_text=stripped
            )
            if ok:
                self._confirmed_profile_fact_count += 1
                return self._complete_conv(
                    state, "conv:relation_updated", build_relation_update_ack(label, new_name)
                )
            return None

        rem = detect_relation_removal_cmd(stripped)
        if rem is not None:
            label, person_name = rem
            existing = find_existing_profile_value(
                ProfileFactCandidate(
                    subject="relation", relation="name",
                    value="", relation_label=label,
                ),
                self._store,
            )
            if existing is None:
                return self._complete_conv(
                    state, "conv:relation_removal_not_found",
                    build_relation_removal_not_found(),
                )
            if self._norm(existing) != self._norm(person_name):
                return self._complete_conv(
                    state, "conv:relation_removal_mismatch",
                    f"Tôi đang nhớ {label} của bạn tên là {existing}, không phải {person_name}.",
                )
            deleted = delete_relation_fact(label, self._store)
            if deleted is not None:
                return self._complete_conv(
                    state, "conv:relation_removed", build_relation_removal_ack(label)
                )
            return None

        return None

    def _maybe_handle_name_correction_text(
        self, remainder: str, state: AgentState
    ) -> AgentState | None:
        """P0-7I: treat remainder as a name UPDATE, bypassing the conflict-safe guard.

        Only used from ``_maybe_handle_correction`` (the caller already stripped a leading
        correction marker). Role/occupation-like values ("blogger") are rejected via the
        same name-shape checks used elsewhere, so a correction never corrupts the stored
        name — the caller falls through to occupation handlers in that case.
        """
        candidate = detect_profile_fact_candidate(remainder)
        if candidate is not None and candidate.subject == "self" and candidate.relation == "name":
            value = candidate.value
        else:
            value = detect_self_name_phrase_update(remainder)
        if value is None:
            return None
        from agent_core.conversation.profile_memory import _is_unsafe_or_sensitive_auto_value
        if _is_unsafe_or_sensitive_auto_value(value):
            return None
        current = collect_profile_snapshot(self._store).name
        if not save_self_name_update(value, self._store, state.session_id, original_text=remainder):
            state.errors.append("profile_save_failed")
            return self._complete_conv(
                state, "conv:profile_autosave_failed",
                "Không thể lưu thông tin. Vui lòng thử lại.",
            )
        self._confirmed_profile_fact_count += 1
        if current is None:
            return self._complete_conv(
                state, "conv:profile_name_saved", f"Đã nhớ tên bạn là {value}."
            )
        return self._complete_conv(
            state, "conv:profile_name_updated", build_name_update_ack(current, value)
        )

    def _maybe_answer_unsupported_memory_domain(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K priority 3.9: honest reply for unsupported/future memory domains.

        Schedule/agenda (P0-7L), historical memory queries (P0-7M), and assistant
        nickname (P0-7N) are classified and answered deterministically — never
        written into profile memory.
        """
        detected = detect_unsupported_memory_domain(user_message.strip())
        if detected is None:
            return None
        domain, response = detected
        return self._complete_conv(state, f"conv:unsupported_{domain}", response)

    # ------------------------------------------------------------------
    # CONV-P0 P0-7K-FIX3 — reminder/repair, delete-all, multi-query, continuation
    # ------------------------------------------------------------------

    _MEMORY_WRITE_HANDLER_NAMES = (
        "_maybe_handle_semantic_extraction",
        "_maybe_handle_memory_operation",
        "_maybe_handle_occupation_removal",
        "_maybe_handle_occupation_correction",
        "_maybe_handle_semantic_profile",
        "_maybe_auto_save_name_relation",
        "_maybe_auto_save_profile_fact",
    )

    def _run_memory_write_pipeline(
        self, text: str, state: AgentState
    ) -> AgentState | None:
        """Run the ordered memory-write handlers on ``text``; first hit wins, else None."""
        for name in self._MEMORY_WRITE_HANDLER_NAMES:
            result = getattr(self, name)(text, state)
            if result is not None:
                return result
        return None

    def _handle_delete_all_pending(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX3 / P0-7K-FIX3-FIX1: resolve a pending delete-all confirmation.

        Priority within the pending state:
        1. Explicit confirmation → clear all profile memory.
        2. Explicit cancel ("không", "hủy", ...) → drop pending, keep memory.
        3. A safe read-only memory query → answer it and KEEP the pending active (an
           intervening summary must NOT silently cancel the delete).
        4. Any other turn → drop the pending (fail-safe: never delete without an explicit
           confirmation) and fall through to normal routing.
        """
        text = user_message.strip()
        if detect_delete_all_confirmation(text):
            self._pending_delete_all = False
            delete_all_profile_memory(self._store)
            self._confirmed_profile_fact_count = 0
            self._last_memory_write_kind = None
            return self._complete_conv(
                state, "conv:memory_deleted_all", build_delete_all_done()
            )
        if _RE_DELETE_CANCEL.match(text):
            self._pending_delete_all = False
            return self._complete_conv(
                state, "conv:memory_delete_cancelled",
                "Đã huỷ yêu cầu xoá ký ức. Mình vẫn giữ thông tin về bạn.",
            )
        # A safe read-only memory query answers normally but keeps the pending active.
        answer = self._answer_single_memory_query(text)
        if answer is not None:
            return self._complete_conv(
                state, "conv:memory_query_while_delete_pending",
                answer + " (Nếu vẫn muốn xoá, hãy trả lời \"xác nhận xoá ký ức\".)",
            )
        # Other non-confirmation turn → drop the pending safely, route normally.
        self._pending_delete_all = False
        return None

    def _maybe_handle_delete_all_request(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX3 K: a delete-all request sets a pending confirmation and asks."""
        if not detect_delete_all_memory_request(user_message.strip()):
            return None
        self._pending_delete_all = True
        return self._complete_conv(
            state, "conv:memory_delete_confirm", build_delete_all_confirmation_prompt()
        )

    def _maybe_handle_stray_delete_confirmation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX3-FIX1: a delete confirmation with NO pending request never deletes
        and never claims success — it says nothing is pending."""
        if self._pending_delete_all:
            return None
        if not detect_delete_all_confirmation(user_message.strip()):
            return None
        return self._complete_conv(
            state, "conv:memory_delete_no_pending",
            "Hiện không có yêu cầu xoá ký ức nào đang chờ xác nhận.",
        )

    def _maybe_handle_reminder_or_repair(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX3 A/B/C/G: reminder with an inner memory clause → re-dispatch the
        inner clause; a standalone repair (or reminder with no clause) → clarification.
        Never saves the raw reminder sentence.
        """
        inner = detect_reminder_inner_clause(user_message.strip())
        if inner is not None:
            result = self._run_memory_write_pipeline(inner, state)
            if result is not None:
                return result
        if detect_repair_intent(user_message.strip()):
            return self._complete_conv(
                state, "conv:repair_clarify", build_repair_clarification()
            )
        return None

    def _answer_single_memory_query(self, part: str) -> str | None:
        """Answer one memory query (profile query or yes/no), else None."""
        query = detect_profile_query(part)
        if query is not None:
            return answer_profile_query(query, self._store)
        intent = classify_profile_semantic_intent(part)
        if intent is not None and intent.kind == "yes_no_memory_query":
            return answer_yes_no_memory_query(
                intent.category or "", intent.value or "", self._store
            )
        return None

    def _maybe_handle_multi_query(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX3 I: answer a batch of simple memory queries in one message.

        Fires only when the message splits into 2+ parts that are ALL supported memory
        queries; otherwise falls through (no broad multi-intent planner).
        """
        parts = [p.strip() for p in re.split(r'[\n;?]+', user_message.strip()) if p.strip()]
        if len(parts) < 2:
            return None
        answers: list[str] = []
        for part in parts:
            ans = self._answer_single_memory_query(part)
            if ans is None:
                return None
            answers.append(f"- {ans}")
        self._last_profile_query_kind = None
        return self._complete_conv(
            state, "conv:multi_query_answered", "\n".join(answers)
        )

    def _maybe_handle_current_state_skill(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX4 C: "(bây giờ) tôi biết X (và Y)" — strip the temporal marker and
        re-dispatch the skill clause so positive skills supersede prior negatives."""
        m = _RE_CURRENT_STATE_SKILL.match(user_message.strip())
        if m is None:
            return None
        return self._run_memory_write_pipeline(m.group(1).strip(), state)

    def _maybe_handle_continuation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX3 H: bounded continuation ("và ML nữa") reusing the last write kind.

        Only fires when the previous turn wrote memory with a clear kind; otherwise the
        bare continuation asks for clarification and writes nothing.
        """
        m = _RE_CONTINUATION.match(user_message.strip())
        if m is None:
            return None
        value = re.sub(r"\s+", " ", m.group(1).strip()).strip()
        if not value:
            return None
        templates = {
            "skill": f"tôi biết {value}",
            "preference": f"tôi thích {value}",
            "negative_preference": f"tôi không thích {value}",
            "goal": f"tôi sẽ làm {value}",
        }
        template = templates.get(self._last_memory_write_kind or "")
        if template is None:
            return self._complete_conv(
                state, "conv:continuation_no_context",
                "Bạn muốn mình nhớ thêm thông tin gì? Hãy nói rõ hơn, "
                'ví dụ: "tôi biết ML" hoặc "tôi thích ML".',
            )
        return self._run_memory_write_pipeline(template, state)

    def _maybe_clarify_relationship_typo(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX1 I: a low-confidence relationship typo ("bạn ái của tôi là quý")
        asks for confirmation instead of writing memory (fail-safe)."""
        detected = detect_relationship_typo(user_message.strip())
        if detected is None:
            return None
        _raw, corrected, name = detected
        return self._complete_conv(
            state, "conv:relationship_typo_clarify",
            build_relationship_typo_clarification(corrected, name),
        )

    def _maybe_handle_semantic_extraction(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K priority 4.11: hybrid semantic extraction for complex utterances.

        The extractor only PROPOSES MemoryOperation[]; low-confidence, erroneous, or
        empty proposals fall through to the deterministic handlers unchanged. Applied
        operations go through validation + conflict resolution in the batch applier.
        """
        text = user_message.strip()
        result = self._semantic_extractor.extract(SemanticExtractionRequest(raw_text=text))
        if result.error or not result.operations:
            return None
        if result.confidence < MIN_EXTRACTION_CONFIDENCE:
            return None
        batch = apply_memory_operations(
            result.operations, self._store, state.session_id, raw_text=text
        )
        if batch.applied == 0 or batch.response_text is None:
            return None
        self._confirmed_profile_fact_count += batch.saved_count
        return self._complete_conv(
            state, "conv:semantic_ops_applied", batch.response_text
        )

    def _maybe_handle_memory_operation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7J priority 4.12: Memory Kernel v1 — parse → validate → resolve → apply.

        Bounded structured update semantics: occupation stop ("tôi không làm X nữa"),
        affection removal ("tôi không thích/yêu/quan tâm X nữa"), relationship
        current-update ("bây giờ người yêu của tôi là X"), and goal add/switch. An
        operation that does not apply to current memory state (e.g. removing an
        affection that is not active) returns None so the turn keeps flowing through
        the normal handler chain unchanged.
        """
        op = parse_memory_operation(user_message.strip())
        if op is None:
            return None
        outcome = apply_memory_operation(op, self._store, state.session_id)
        if outcome is None:
            return None
        if outcome.saved:
            self._confirmed_profile_fact_count += 1
        return self._complete_conv(state, outcome.trace_marker, outcome.response_text)

    def _maybe_handle_occupation_removal(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7I: retract a stored occupation ("tôi không phải nông dân").

        Only fires when the extracted value matches a CURRENTLY stored occupation
        (case-insensitive); unrelated denials fall through untouched.
        """
        value = detect_occupation_removal(user_message.strip())
        if value is None:
            return None
        removed = delete_occupation_fact(value, self._store)
        if removed is None:
            return None
        return self._complete_conv(
            state, "conv:occupation_removed", build_occupation_removal_ack(removed)
        )

    def _maybe_handle_correction(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7I priority 4.1: strip a leading correction phrase ("không, ", "ý tôi là ",
        "tôi mới/vừa nói ... mà") and re-dispatch the remainder through the normal write
        detectors, so a correction is understood instead of falling to a generic fallback.
        """
        remainder = detect_correction_remainder(user_message.strip())
        if remainder is None:
            return None
        for handler in (
            self._maybe_handle_occupation_removal,
            self._maybe_handle_name_correction_text,
            self._maybe_handle_occupation_correction,
            self._maybe_handle_semantic_profile,
            self._maybe_auto_save_name_relation,
            self._maybe_auto_save_profile_fact,
        ):
            result = handler(remainder, state)
            if result is not None:
                return result
        return None

    def _maybe_handle_occupation_correction(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7H-FIX1 priority 4.2: occupation/name correction.

        "không tôi làm nông là nông dân chứ không phải tên tôi là nông dân"
        → save occupation, leave name unchanged, return specific ack.
        """
        value = detect_occupation_name_correction(user_message.strip())
        if value is None:
            return None
        candidate = AutoProfileCandidate(
            subject="self", relation="occupation", value=value,
            original_text=user_message.strip(),
        )
        ok = save_auto_profile_fact(candidate, self._store, state.session_id)
        if not ok:
            return None
        self._confirmed_profile_fact_count += 1
        return self._complete_conv(
            state, "conv:occ_correction_saved", build_occ_correction_ack(value)
        )

    def _maybe_handle_semantic_profile(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7F: dispatch a semantically-classified profile turn, or None to fall through."""
        intent = classify_profile_semantic_intent(user_message.strip())
        if intent is None:
            return None

        if intent.kind == "clarification_followup":
            return self._complete_conv(
                state, "conv:profile_followup",
                build_followup_response(self._has_recent_profile_query()),
            )

        if intent.kind == "yes_no_memory_query":
            self._profile_query_context_turn = len(self._session.turns)
            answer = answer_yes_no_memory_query(
                intent.category or "", intent.value or "", self._store
            )
            return self._complete_conv(state, "conv:profile_yes_no_answered", answer)

        if intent.kind != "profile_write":
            return None

        # --- profile_write dispatch by policy ---
        if intent.write_policy == "block":
            return self._complete_conv(
                state, "conv:unsafe_profile_value_blocked",
                build_blocked_value_response(
                    BlockedProfileAttempt(
                        relation=intent.category or "", value=intent.value or ""
                    )
                ),
            )
        if intent.write_policy == "clarify":
            # Category-specific clarifications take precedence over the generic
            # person-affinity response (both carry person_affinity sensitivity).
            if intent.category == "negation_no_affection":
                return self._complete_conv(
                    state, "conv:negation_no_affection",
                    build_negation_no_affection_response(),
                )
            if intent.category == "negative_desire":
                return self._complete_conv(
                    state, "conv:negative_desire",
                    build_negative_desire_response(intent.value or ""),
                )
            if intent.category == "affection_explanation":
                return self._complete_conv(
                    state, "conv:affection_explanation",
                    build_affection_explanation_response(intent.value or ""),
                )
            if intent.category == "affection_relation":
                return self._complete_conv(
                    state, "conv:affection_relation",
                    build_affection_relation_response(intent.value or ""),
                )
            if intent.category == "one_sided_affection":
                return self._complete_conv(
                    state, "conv:one_sided_affection",
                    build_one_sided_affection_response(intent.value or ""),
                )
            if intent.sensitivity == "person_affinity":
                return self._complete_conv(
                    state, "conv:person_affinity_clarify",
                    build_person_affinity_response(intent.value or ""),
                )
            return self._complete_conv(
                state, "conv:profile_near_miss",
                build_near_miss_response(intent.value or ""),
            )

        # write_policy == "auto_safe"
        if intent.category == "relationship.partner_name":
            return self._handle_semantic_relationship(intent, user_message, state)

        # P0-7K-FIX2: favorite ("tôi thích X nhất") — stored distinctly, never as an
        # ordinary preference.
        if intent.category and intent.category.startswith("favorite."):
            value = intent.value or ""
            domain = intent.category.split(".", 1)[1]
            if not save_favorite_fact(
                value, domain, self._store, state.session_id,
                original_text=user_message.strip(),
            ):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:favorite_saved",
                f"Đã nhớ là bạn thích {value} nhất.",
            )

        # P0-7K-FIX2: comparative ("tôi thích A hơn B") — stored distinctly.
        if intent.category and intent.category.startswith("comparative."):
            winner = intent.value or ""
            loser = intent.relation_label or ""
            domain = intent.category.split(".", 1)[1]
            if not save_comparative_fact(
                winner, loser, domain, self._store, state.session_id,
                original_text=user_message.strip(),
            ):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:comparative_saved",
                f"Đã nhớ là bạn thích {winner} hơn {loser}.",
            )

        # P0-7G: affection/person memory ("tôi thích/yêu/crush Quý") — saved distinctly.
        if intent.category in ("relationship.affection_candidate", "affection_relation"):
            value = intent.value or ""
            if not save_affection_fact(
                value, self._store, state.session_id, original_text=user_message.strip()
            ):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:affection_saved", build_affection_memory_ack(value)
            )

        # P0-7G: user-reported external affection ("Quý thích tôi"/"Quý thích Bắc").
        if intent.category == "external_affection":
            return self._handle_external_affection(intent, user_message, state)

        # P0-7G: durable negative preference ("tôi không thích ăn cá").
        if intent.category == "negative_preference":
            value = intent.value or ""
            # P0-7I: a new negative preference supersedes a conflicting active positive
            # preference for the same object (memory conflict resolution).
            resolve_preference_conflicts(value, "negative_preference", self._store)
            candidate = AutoProfileCandidate(
                relation="negative_preference", value=value,
                original_text=user_message.strip(),
            )
            if not save_auto_profile_fact(candidate, self._store, state.session_id):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:negative_preference_saved",
                build_negative_preference_ack(value),
            )

        candidate = self._semantic_to_auto_candidate(intent, user_message.strip())
        if candidate is None:
            return None
        # P0-7I: a new positive preference supersedes a conflicting active dislike for
        # the same object (memory conflict resolution).
        if candidate.relation == "preference":
            resolve_preference_conflicts(candidate.value, "preference", self._store)
        # P0-7K-FIX1: skill positive/negative conflict resolution (latest polarity wins).
        if candidate.relation in ("skill", "negative_skill"):
            resolve_skill_conflicts(candidate.value, candidate.relation, self._store)
        # P0-7K-FIX1: goal memory is an active MULTI-goal set — a plain new goal is ADDED
        # (no supersede); dedup an exact repeat so it is not stored twice.
        if candidate.relation == "goal" and goal_already_active(candidate.value, self._store):
            return self._complete_conv(
                state, "conv:semantic_profile_saved", build_auto_ack_message(candidate)
            )
        ok = save_auto_profile_fact(candidate, self._store, state.session_id)
        if not ok:
            return None
        self._confirmed_profile_fact_count += 1
        # P0-7K-FIX3: record the write kind for a bounded continuation ("và ML nữa").
        _CONTINUATION_KINDS = {
            "skill": "skill", "preference": "preference", "goal": "goal",
        }
        if candidate.relation in _CONTINUATION_KINDS:
            self._last_memory_write_kind = _CONTINUATION_KINDS[candidate.relation]
        if candidate.relation == "negative_skill":
            return self._complete_conv(
                state, "conv:negative_skill_saved",
                build_negative_skill_ack(candidate.value),
            )
        return self._complete_conv(
            state, "conv:semantic_profile_saved", build_auto_ack_message(candidate)
        )

    def _maybe_handle_exact_name_external_affection(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7G-FIX4B: exact saved-name fallback for 3+ token self-names.

        profile_semantics._RE_EXTERNAL_AFFECTION is bounded to 1-2 token objects to avoid
        overmatching long phrases. For saved names with 3+ tokens (e.g. "Nguyễn Văn Bắc"),
        match the object exactly against the saved name via _norm comparison.
        """
        current = collect_profile_snapshot(self._store).name
        if not current or len(current.split()) < 3:
            return None
        m = _RE_EXTERNAL_AFFECTION_LOOSE.match(user_message.strip())
        if not m:
            return None
        admirer = m.group(1).strip()
        obj = m.group(2).strip()
        if admirer.lower() in _EXTERNAL_AFFECTION_SELF_WORDS:
            return None
        if self._norm(obj) != self._norm(current):
            return None
        if not save_external_affection_fact(
            admirer, self._store, state.session_id, original_text=user_message.strip()
        ):
            return None
        self._confirmed_profile_fact_count += 1
        return self._complete_conv(
            state, "conv:external_affection_saved", build_external_affection_ack(admirer)
        )

    def _handle_external_affection(
        self, intent: SemanticProfileIntent, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7G: save a user-reported external affection fact only when its object is the
        current user (a self word or the saved self-name). Otherwise fall through."""
        admirer = intent.value or ""
        obj = (intent.relation_label or "").strip()
        current = collect_profile_snapshot(self._store).name
        obj_is_user = (
            obj.lower() in _EXTERNAL_AFFECTION_SELF_WORDS
            or (current is not None and self._norm(obj) == self._norm(current))
        )
        if not obj_is_user:
            # P0-7G-FIX1: unrelated third-party affection ("Quý thích Nam") — narrow
            # safe/no-save reply instead of the generic rule-based fallback.
            return self._complete_conv(
                state, "conv:unrelated_external_affection",
                build_unrelated_external_affection_response(admirer, obj),
            )
        if not save_external_affection_fact(
            admirer, self._store, state.session_id, original_text=user_message.strip()
        ):
            return None
        self._confirmed_profile_fact_count += 1
        return self._complete_conv(
            state, "conv:external_affection_saved", build_external_affection_ack(admirer)
        )

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
