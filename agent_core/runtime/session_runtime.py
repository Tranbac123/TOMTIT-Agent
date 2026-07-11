from __future__ import annotations

import dataclasses
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from agent_core.conversation.capabilities import (
    Capability,
    CapabilityRouter,
)
from agent_core.conversation.llm_responder import (
    BoundedLLMResponder,
    LLMResponderRequest,
    LLMResponse,
    LLMResponseRequest,
    RuleBasedLLMResponder,
    TextLLMResponder,
)
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
    build_answer_feedback_repair,
    build_generic_reminder_repair,
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
    canonical_person_name,
    detect_delete_all_confirmation,
    detect_delete_all_confirmation_pending,
    detect_delete_all_memory_request,
    detect_reminder_inner_clause,
    detect_answer_feedback,
    detect_generic_reminder,
    detect_repair_intent,
    detect_relation_alias_query,
    detect_relation_removal_cmd,
    detect_relation_update_cmd,
    detect_relationship_typo,
    detect_self_name_phrase_update,
    detect_self_name_ten_assertion,
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
    save_negative_affection_fact,
    save_negative_external_affection_fact,
    save_relation_update,
    save_self_name_update,
    save_temporal_today_fact,
    save_intention_goal_fact,
    save_negative_goal_fact,
    delete_temporal_today_fact,
    delete_wants_to_eat_fact,
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
from agent_core.runtime.turn_trace import TurnTrace
from agent_core.safety.capability_gate import ActionRisk, CapabilitySafetyGate
from agent_core.tools.runtime import ToolRuntime, ToolRuntimeRequest
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

# CONV-P0 P0-7K-FIX7-LITE D: today-scoped intention write ("hôm nay tôi muốn build AI") and
# retraction ("hôm nay tôi không muốn build AI nữa"). Only "hôm nay" is supported.
_RE_TEMPORAL_TODAY_WRITE = re.compile(
    r'^hôm\s+nay\s+(?:tôi|mình)\s+(?:đang\s+)?muốn\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE,
)
_RE_TEMPORAL_TODAY_REMOVE = re.compile(
    r'^hôm\s+nay\s+(?:tôi|mình)\s+không\s+muốn\s+(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE,
)
# CONV-P0 P0-7K-FIX7-LITE C: eating-desire retraction ("tôi không muốn ăn kem nữa").
_RE_STOP_EAT = re.compile(
    r'^(?:tôi|mình)\s+không\s+muốn\s+ăn\s+(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 A: today-scoped intention understood in prefix OR suffix position and
# across intention verbs (muốn/sẽ/định/dự định). The "hôm nay" gate is applied by the
# handler; these patterns capture the raw plan (which may still carry a "hôm nay" token to
# be stripped) so a dirty generic goal ("làm LLM hôm nay") is never stored.
_FIX8_INTENT_VERBS = r'(?:muốn|sẽ|định|dự\s+định)'
_RE_FIX8_TODAY_REMOVE = re.compile(
    r'^(?:hôm\s+nay\s+)?(?:tôi|mình)\s+không\s+' + _FIX8_INTENT_VERBS + r'\s+(.+?)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_RE_FIX8_TODAY_WRITE = re.compile(
    r'^(?:hôm\s+nay\s+)?(?:tôi|mình)\s+(?:đang\s+)?' + _FIX8_INTENT_VERBS + r'\s+(.+?)\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 C/D: durable intention alias ("tôi định/dự định làm X") and its
# retraction ("tôi không định/muốn làm X nữa"). Requires an explicit "làm|build" head so
# eating/affection desires are untouched. "hôm nay" forms are handled by the temporal lane;
# the bare "sẽ làm"/"muốn làm" writes already flow through the existing goal pipeline (which
# owns dedup / goal-switch / AI-taxonomy split), so they are deliberately NOT matched here.
_RE_FIX8_INTENT_WRITE = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?(?:định|dự\s+định)\s+((?:làm|build)\s+.+?)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_RE_FIX8_INTENT_REMOVE = re.compile(
    r'^(?:tôi|mình)\s+không\s+(?:muốn|định|dự\s+định)\s+((?:làm|build)\s+.+?)'
    r'(?:\s+nữa)?\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 E: yes/no query about today's plan, tolerant of the narrow "cps" typo
# for "có" ("tôi cps muốn làm LLM hôm nay không?").
_RE_FIX8_TODAY_YESNO = re.compile(
    r'^(?:tôi|mình)\s+(?:có|cps)\s+(?:muốn\s+|định\s+|sẽ\s+)?(?:làm|build)\s+(.+?)\s+'
    r'hôm\s+nay\s+(?:không|ko|hông|hong)\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 G: historical preference query ("tôi có/đã từng thích ăn kem không/chưa?").
_RE_FIX8_HISTORICAL_LIKE = re.compile(
    r'^(?:tôi|mình)\s+(?:có|đã)\s+từng\s+thích\s+(.+?)\s+(?:không|ko|chưa|chua)\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 H / P0-7K-FIX8-R1 A: mutual-affection factual query, symmetric in the
# USER/person order — "tôi và X", "X và tôi", "tôi với X", "X với tôi" all resolve to the
# same USER<->X mutual question. The person is captured by whichever named group matched.
_RE_FIX8_MUTUAL_LIKE = re.compile(
    r'^(?:'
    r'(?:tôi|mình)\s+(?:và|với)\s+(?P<a>.+?)'
    r'|(?P<b>.+?)\s+(?:và|với)\s+(?:tôi|mình)'
    r')\s+có\s+(?:thích|yêu|quý\s+mến)\s+nhau\s+'
    r'(?:không|ko|hông|hong)\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 M: relationship ADVICE ("tôi với quý có nên yêu nhau không?"). "nên"
# marks advice (not a factual mutual query); answered as a bounded limitation.
_RE_FIX8_RELATION_ADVICE = re.compile(
    r'^(?:tôi|mình)\s+(?:và|với)\s+(.+?)\s+có\s+nên\s+(?:yêu|cưới|hẹn\s+hò|quen)\s+'
    r'(?:nhau)?\s*(?:không|ko|hông|hong)\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 K: double affection query ("ai đang thích tôi và tôi đang thích ai?").
_RE_FIX8_DOUBLE_AFFECTION_Q = re.compile(
    r'^ai\s+(?:đang\s+)?th[íi]ch\s+(?:tôi|mình)\s+và\s+(?:tôi|mình)\s+(?:đang\s+)?'
    r'th[íi]ch\s+ai\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 I: compound relation write ("may cũng thích tôi và tôi cũng thích may").
# Two clauses joined by "và"; one incoming (person→USER), one outgoing (USER→person).
_RE_FIX8_COMPOUND_RELATION = re.compile(
    r'^(.+?)\s+và\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE,
)
_RE_FIX8_INCOMING_CLAUSE = re.compile(
    r'^(\S+(?:\s+\S+)?)\s+(?:cũng\s+|vẫn\s+|đang\s+)?(?:thích|yêu|thương|quý\s+mến)\s+'
    r'(tôi|mình|tao|ta)\s*$',
    re.IGNORECASE,
)
_RE_FIX8_OUTGOING_CLAUSE = re.compile(
    r'^(?:tôi|mình|tao|ta)\s+(?:cũng\s+|vẫn\s+|đang\s+)?(?:thích|yêu|thương|quý\s+mến)\s+'
    r'(\S+(?:\s+\S+)?)\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 J: continuation adding an admirer ("cả may nữa"/"may nữa"/"thêm may
# nữa"). With incoming-affection context it stores the admirer; without it, it asks a named
# clarification (P0-7K-FIX8-FIX1). The negative lookahead excludes a "và ..." lead-in, which
# is the generic skill/preference/goal continuation marker (_RE_CONTINUATION) and must stay
# on that lane untouched (e.g. "và ML nữa" after "tôi biết về AI").
_RE_FIX8_CONTINUATION_ADMIRER = re.compile(
    r'^(?:cả\s+|thêm\s+)?(?!và\s)(\S+(?:\s+\S+)?)\s+nữa\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX8 N: future-date plan query ("ngày mai tôi muốn làm gì?"). Only "hôm nay"
# is supported; a bounded limitation is returned for other dates.
_RE_FIX8_FUTURE_DATE_Q = re.compile(
    r'^(ngày\s+mai|mai|ngày\s+kia|tuần\s+sau|tháng\s+sau)\s+(?:tôi|mình)\s+'
    r'(?:muốn|sẽ|định)\s+làm\s+g[ìi]\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K xfail-burndown P3: memory-edge patterns (goal-read variant, imperative
# remember, vague forget, disable-memory-for-turn, assumption/provenance query).
# memory_002: "Bạn (có) biết mục tiêu hiện tại của tôi (là gì) (không)?"
_RE_GOAL_CONFIRM_Q = re.compile(
    r'^bạn\s+(?:có\s+)?biết\s+mục\s+tiêu\s+(?:hiện\s+tại\s+)?(?:của\s+)?(?:tôi|mình)\s*'
    r'(?:là\s+g[ìi])?\s*(?:không|ko)?\s*[?？]*\s*$',
    re.IGNORECASE,
)
# memory_003: "Hãy (ghi) nhớ (giúp tôi) rằng/là <content>" — imperative confirmed write.
_RE_IMPERATIVE_REMEMBER = re.compile(
    r'^(?:hãy\s+)?(?:ghi\s+)?nhớ\s+(?:giúp\s+(?:tôi|mình)\s+)?(?:rằng|là)\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE,
)
# memory_004: "Hãy quên thông tin/cái/điều đó/này (đi)" — vague, no resolvable target.
_RE_VAGUE_FORGET = re.compile(
    r'^(?:hãy\s+)?quên\s+(?:thông\s+tin|cái|điều)\s+(?:đó|này|ấy|kia)\s*(?:đi)?\s*[.!?]*\s*$',
    re.IGNORECASE,
)
# memory_005: "Đừng dùng memory/trí nhớ (trong) câu trả lời này/lần này".
_RE_DISABLE_MEMORY_TURN = re.compile(
    r'^đừng\s+dùng\s+(?:memory|trí\s+nhớ|bộ\s+nhớ|thông\s+tin\s+đã\s+nhớ)\b.*'
    r'(?:câu\s+(?:trả\s+lời|này)|lần\s+này|turn\s+này|trả\s+lời\s+này).*$',
    re.IGNORECASE,
)
# memory_006: "Thông tin nào (về tôi) là assumption/giả định?".
_RE_ASSUMPTION_QUERY = re.compile(
    r'^(?:thông\s+tin|cái|điều)\s+(?:g[ìi]|nào)\s+(?:về\s+)?(?:tôi|mình)\s+'
    r'là\s+(?:assumption|giả\s+định|suy\s+đoán|suy\s+diễn)\s*[?？]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K xfail-burndown P4: LLM-forbidden requests get a truthful current-MVP
# limitation (LLMResponder is not configured; no plan/translation/explanation is generated).
# Deliberately NARROW so they do not shadow the general LLM-explanation lane
# ("giải thích AI là gì?" stays LLM_RESPONSE) or the spy-responder translation test
# ('dịch "hello" sang tiếng Việt').
# Full plan/roadmap/focus-strategy requests.
_RE_P4_PLANNING = re.compile(
    r'(?:lên|lập|tạo)\s+(?:kế\s+hoạch|lộ\s+trình)'
    r'|\broadmap\b'
    r'|\d+\s+tiếng\b'
    r'|quá\s+tải',
    re.IGNORECASE,
)
# Translation of a provided passage ("Dịch đoạn này ..."); the quoted-literal translation
# test ('dịch "hello" sang tiếng Việt') has no "đoạn" and stays on the LLM lane.
_RE_P4_TRANSLATION = re.compile(
    r'^d[ịi]ch\s+đoạn\b',
    re.IGNORECASE,
)
# Architecture design ("thiết kế architecture ...").
_RE_P4_TECHNICAL_DESIGN = re.compile(
    r'thiết\s+kế\s+architecture', re.IGNORECASE,
)
# A technical explain/compare request naming the internal runtime components. Two shapes
# both need the (unavailable) LLMResponder for a real answer, so both get the bounded P4
# limitation:
#   - full explanation naming ALL four (code_005: "giải thích Planner, Runtime, Tool,
#     Memory khác nhau thế nào");
#   - a comparison ("phân biệt"/"so sánh"/"khác gì"/"khác nhau") of at least TWO of them
#     ("phân biệt Planner và Runtime", "so sánh Tool và Memory").
# A single-component "giải thích Planner là gì" and a plain "giải thích AI là gì?" are NOT
# matched (they stay on their existing lanes).
_P4_TECHNICAL_COMPONENTS = ("planner", "runtime", "tool", "memory")
_P4_TECHNICAL_COMPARE_CUES = ("phân biệt", "so sánh", "khác gì", "khác nhau")


def _is_p4_technical_components_request(text: str) -> bool:
    low = text.lower()
    present = sum(1 for c in _P4_TECHNICAL_COMPONENTS if c in low)
    if any(v in low for v in ("giải thích", "phân biệt", "so sánh")) and present == 4:
        return True
    if any(cue in low for cue in _P4_TECHNICAL_COMPARE_CUES) and present >= 2:
        return True
    return False

# CONV-P0 P0-7K-FIX6-LITE G: coordinated external affection ("may và quý đều thích tôi").
# The "đều" marker signals multiple person→USER edges; subjects (group1) split on "và"/",".
_RE_COORDINATED_EXTERNAL_AFFECTION = re.compile(
    r'^(.+?(?:\s*,\s*|\s+và\s+).+?)\s+(?:đều\s+)?(?:cũng\s+|vẫn\s+|đang\s+)?'
    r'(?:thích|yêu|thương|quý\s+mến|quan\s+tâm(?:\s+(?:đến|tới))?)\s+'
    r'(\S+)\s*[.!]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX5C-LITE G: affection statement whose subject is an old/current self
# alias ("bây giờ bắc thích quý"). Optional temporal marker; group1=subject, group2=verb,
# group3=object. When the subject resolves to the user, the sentence is rewritten to
# first person and re-dispatched, so person-vs-preference disambiguation is reused.
_RE_ALIAS_AFFECTION_STMT = re.compile(
    r'^(?:(?:bây\s+giờ|hiện\s+tại|giờ|từ\s+nay)\s*,?\s+)?'
    r'(\S+(?:\s+\S+)?)\s+(?:cũng\s+|vẫn\s+|đang\s+)?'
    r'(thích|yêu|thương|quý\s+mến|quan\s+tâm(?:\s+(?:đến|tới))?)\s+'
    r'(\S+(?:\s+\S+)?)\s*[.!]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-7K-FIX5A: obvious meta-feedback about a prior answer. This is not a memory
# write and not a full repair system; it simply avoids fallback/pollution.
_RE_PROFILE_FEEDBACK_NO_WRITE = re.compile(
    r'(?:'
    r'bạn\s+phải\s+trả\s+lời\s+là'
    r'|bạn\s+trả\s+lời\s+sai\s+rồi'
    r'|trả\s+lời\s+sai\s+rồi'
    r'|không\s+phải\s+(?:là\s+)?không\s+biết'
    r'|phải\s+nói\s+là'
    r')',
    re.IGNORECASE,
)
_PROFILE_FEEDBACK_NO_WRITE_RESPONSE = (
    "Mình hiểu là câu trả lời trước chưa đúng. Bạn nói rõ thông tin cần sửa để "
    "mình cập nhật cho đúng nhé."
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
        bounded_responder: BoundedLLMResponder | None = None,
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
        # CONV-P0 P0-8A: capability backbone. Deterministic router + bounded responder +
        # safety gate + tool-runtime scaffold. The bounded responder is response-only by
        # construction (it receives only the user text/payload — never memory, tools, or
        # state) and is injectable for tests.
        self._capability_router = CapabilityRouter()
        self._bounded_responder: BoundedLLMResponder = (
            bounded_responder if bounded_responder is not None else RuleBasedLLMResponder()
        )
        self._capability_safety_gate = CapabilitySafetyGate()
        self._capability_tool_runtime = ToolRuntime(gate=self._capability_safety_gate)
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
        # P0-7K-HOTFIX1 F: last answered profile query, for answer-feedback re-answering.
        self._last_answered_query: ProfileQuery | None = None
        # CONV-P0 P0-7K-FIX3: bounded continuation context ("và ML nữa") + delete-all
        # pending confirmation. Session-local only, never persisted.
        self._last_memory_write_kind: str | None = None
        self._pending_delete_all: bool = False
        # P0-7K-FIX8 L: set after the repair-choice prompt ("... sửa phần nào: ... quan hệ?")
        # so a bare choice ("quan hệ") gets a sub-clarification instead of a fallback.
        self._pending_repair_choice: bool = False
        # P0-8A: per-turn observability. handle_turn() resets these, the capability/safety
        # handlers fill them, and the wrapper publishes an immutable TurnTrace snapshot.
        self.last_trace: TurnTrace | None = None
        self._turn_capability: str | None = None
        self._turn_route: str | None = None
        self._turn_safety: str | None = None
        self._turn_tool_name: str | None = None
        self._turn_tool_ok: bool | None = None
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
        """Public turn entrypoint (unchanged contract) + P0-8A trace publication.

        Resets the per-turn trace fields, dispatches to the existing handler chain, then
        publishes an immutable ``TurnTrace`` on ``self.last_trace``. Behavior and the
        returned ``AgentState`` are identical to the pre-P0-8A implementation.
        """
        self._turn_capability = None
        self._turn_route = None
        self._turn_safety = None
        self._turn_tool_name = None
        self._turn_tool_ok = None
        facts_before = self._confirmed_profile_fact_count
        state = self._handle_turn_impl(user_message)
        facts_delta = self._confirmed_profile_fact_count - facts_before
        memory_diff = (
            [f"confirmed_profile_facts:{facts_delta:+d}"] if facts_delta else []
        )
        route = self._turn_route
        if route is None:
            # Derive the route from the conversation markers the handlers already record,
            # preferring the specific handler marker over the terminal state_finalized one.
            route = next(
                (
                    h for h in reversed(state.history)
                    if h.startswith("conv:") and h != "conv:state_finalized"
                ),
                None,
            ) or next(
                (h for h in reversed(state.history) if h.startswith("conv:")), None
            )
        self.last_trace = TurnTrace(
            user_text=user_message,
            normalized_text=user_message.strip(),
            capability=self._turn_capability,
            route=route,
            safety_decision=self._turn_safety,
            memory_diff=memory_diff,
            tool_name=self._turn_tool_name,
            tool_ok=self._turn_tool_ok,
            final_answer=state.final_answer or "",
        )
        return state

    def _handle_turn_impl(self, user_message: str) -> AgentState:
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

        # CONV-P0 P0-7K xfail-burndown P3 priority 1.45: bounded memory-edge turns
        # (goal-read variant, imperative remember, vague forget, disable-memory-for-turn,
        # assumption/provenance query). Before delete-all so a vague "quên thông tin đó"
        # is clarified, never routed to any deletion.
        memory_edge = self._maybe_handle_memory_edge(user_message, state)
        if memory_edge is not None:
            return memory_edge

        # CONV-P0 P0-8A priority 1.452: external tool-action requests (send email / create
        # calendar event / delete file) → safety gate. Nothing executes in MVP; the answer
        # is a bounded confirmation-needed/limitation response. Before the profile writers
        # so an imperative like "gửi email cho Nam là hello" is never misread as a memory
        # write.
        external_action = self._maybe_handle_external_action_request(user_message, state)
        if external_action is not None:
            return external_action

        # CONV-P0 P0-8A priority 1.455: response-only capability requests (translation /
        # technical explanation / checklist / prioritization / rewrite / summary) → bounded
        # LLMResponder. Placed before the P4 limitation lane so a payload-carrying request
        # gets a bounded answer instead of the ask-for-input limitation; payload-less
        # checklist/prioritization forms fall through to the existing clarification lanes.
        capability_response = self._maybe_handle_capability_response(user_message, state)
        if capability_response is not None:
            return capability_response

        # CONV-P0 P0-7K xfail-burndown P4 priority 1.46: LLM-forbidden requests (full plan /
        # translation / technical design) → truthful current-MVP limitation. Placed before
        # the affection/profile handlers so a narrow request like "Giải thích Planner,
        # Runtime, Tool, Memory" (which contains "thích" inside "giải thích") is not misread
        # as an affection write. Narrow patterns only; the general LLM-explanation lane
        # ("giải thích AI là gì?") and the responder path are untouched.
        llm_forbidden = self._maybe_handle_llm_forbidden_limitation(user_message, state)
        if llm_forbidden is not None:
            return llm_forbidden

        # CONV-P0 P0-7K-FIX3 priority 1.5: delete-all memory request → set pending, confirm.
        delete_req = self._maybe_handle_delete_all_request(user_message, state)
        if delete_req is not None:
            return delete_req

        # CONV-P0 P0-7K-FIX3-FIX1 priority 1.55: a stray delete confirmation with no
        # pending request must not delete or claim success.
        stray_confirm = self._maybe_handle_stray_delete_confirmation(user_message, state)
        if stray_confirm is not None:
            return stray_confirm

        # CONV-P0 P0-7K-FIX8 L priority 1.52: resolve a pending repair-choice ("quan hệ")
        # after the "... sửa phần nào?" prompt with a bounded follow-up, never a fallback.
        repair_choice = self._maybe_handle_repair_choice(user_message, state)
        if repair_choice is not None:
            return repair_choice

        # CONV-P0 P0-7K-FIX8 F priority 1.55: embedded self-correction ("... có nghĩa là tôi
        # muốn làm Chatbox") — extract only the trailing intended fact. Before the
        # reminder/repair lane, which would otherwise re-dispatch the meta wrapper into the
        # near-miss clarifier and store a dirty object.
        fix8_correction = self._maybe_handle_fix8_embedded_correction(user_message, state)
        if fix8_correction is not None:
            return fix8_correction

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

        # CONV-P0 P0-7K-FIX8 J priority 1.78: continuation adding an admirer ("cả may nữa")
        # right after an incoming-affection query. Gated on the last answered query kind, so
        # it never fires without that context; before the generic continuation clarifier.
        fix8_admirer = self._maybe_handle_fix8_continuation_admirer(user_message, state)
        if fix8_admirer is not None:
            return fix8_admirer

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

        # CONV-P0 P0-7K-FIX5A priority 3.95: answer-feedback/no-write guard. Runs before
        # profile reads/writes so feedback text cannot be stored as a preference.
        feedback = self._maybe_handle_profile_feedback_no_write(user_message, state)
        if feedback is not None:
            return feedback

        # CONV-P0 P0-7K-FIX8 E/G/H/K/M/N priority 3.98: bounded relation/temporal factual
        # queries (today yes/no, historical like, mutual, double, advice limitation, future
        # date). Before profile query so they are not misread as generic yes/no or fallback.
        fix8_query = self._maybe_handle_fix8_relation_queries(user_message, state)
        if fix8_query is not None:
            return fix8_query

        # CONV-P0 P0-7B priority 4: profile query — answer from confirmed facts before router.
        profile_answer = self._maybe_answer_profile_query(user_message, state)
        if profile_answer is not None:
            return profile_answer

        # CONV-P0 P0-7K-FIX7-LITE priority 4.02: today-scoped intention write/retraction and
        # eating-desire retraction. After the profile-query answer (which owns the "hôm nay
        # ... làm gì?" and "muốn ăn gì?" query forms), before the general desire writers.
        temporal = self._maybe_handle_temporal_today(user_message, state)
        if temporal is not None:
            return temporal

        # CONV-P0 P0-7K-FIX8 C/D priority 4.025: durable intention alias ("tôi định làm
        # Chatbox") and its retraction ("tôi không định làm Agent nữa"). After the temporal
        # (today) lane, before the general desire writers/semantic layer.
        fix8_intention = self._maybe_handle_fix8_intention_goal(user_message, state)
        if fix8_intention is not None:
            return fix8_intention

        stop_eat = self._maybe_handle_stop_eat(user_message, state)
        if stop_eat is not None:
            return stop_eat

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

        # CONV-P0 P0-7K-FIX8 I priority 4.105: compound relation write ("may cũng thích tôi
        # và tôi cũng thích may") → both a person→USER and a USER→person edge. Before the
        # semantic extractor, which otherwise stores "tôi" as a liked person and drops the
        # incoming edge.
        fix8_compound = self._maybe_handle_fix8_compound_relation(user_message, state)
        if fix8_compound is not None:
            return fix8_compound

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

        # CONV-P0 P0-7K-FIX6-LITE priority 4.44: coordinated external affection
        # ("may và quý đều thích tôi") → one person→USER edge per subject.
        coord_aff = self._maybe_handle_coordinated_external_affection(user_message, state)
        if coord_aff is not None:
            return coord_aff

        # CONV-P0 P0-7K-FIX5C-LITE priority 4.45: an affection statement whose subject is an
        # old/current self alias ("bây giờ bắc thích quý") → rewrite to first person and
        # re-dispatch as a self-affection write. Before the semantic layer, which would
        # otherwise read the name-subject as an (unrelated) external affection.
        alias_aff = self._maybe_handle_alias_affection_statement(user_message, state)
        if alias_aff is not None:
            return alias_aff

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
        """Return a completed AgentState if the message is a profile query."""
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
        # P0-7K-FIX5B-FIX2: even with zero saved facts, profile_summary must answer
        # from the profile layer's clean empty-state response. Falling through to the
        # generic runtime fallback mentions runtime/memory/tool and can look like
        # technical-topic pollution after a no-write explanation request.
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
        # P0-7K-HOTFIX1 F: remember the last answered query so answer-feedback can re-answer.
        self._last_answered_query = query
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

        # P0-7K-HOTFIX1 A: a natural "tên" assertion ("bây giờ tôi tên là BB", "tên tôi
        # là BB") is an explicit UPDATE to an existing name. A first-time "tôi tên là X"
        # (no stored name) is left to the downstream confirm/conflict path so its save
        # still flows through save_confirmed_profile_fact.
        new_name = detect_self_name_ten_assertion(text) if current is not None else None
        if new_name is None:
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

    # ------------------------------------------------------------------
    # CONV-P0 P0-8A — capability backbone handlers
    # ------------------------------------------------------------------

    _EXTERNAL_ACTION_RESPONSES: dict[str, str] = {
        "send_email": (
            "Mình chưa hỗ trợ gửi email trong MVP này — hành động external cần xác nhận "
            "và tool chưa được bật, nên mình không gửi gì cả (không có email nào được gửi)."
        ),
        "send_message": (
            "Mình chưa hỗ trợ gửi tin nhắn trong MVP này — hành động external cần xác "
            "nhận và tool chưa được bật, nên mình không gửi gì cả."
        ),
        "create_calendar_event": (
            "Mình chưa hỗ trợ đặt lịch/calendar trong MVP này, nên mình không tạo sự "
            "kiện hay lời nhắc nào."
        ),
        "delete_file": (
            "Mình không thể xoá file — đây là hành động không thể hoàn tác, chưa hỗ trợ "
            "trong MVP này, và mình sẽ không thực hiện."
        ),
    }

    def _maybe_handle_external_action_request(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-8A: external tool-action requests (email/message/calendar/file deletion).

        The request is run through the safety-gated tool runtime, which blocks it before
        any execution (the stubs also have no implementation). The user gets a bounded
        confirmation-needed/limitation answer; nothing is sent, created, or deleted.
        """
        match = self._capability_router.classify(user_message)
        if match.capability is not Capability.TOOL_ACTION_REQUEST or match.tool_name is None:
            return None
        result = self._capability_tool_runtime.run(
            ToolRuntimeRequest(tool_name=match.tool_name)
        )
        # The scaffold must never execute an external action; fail closed if it somehow did.
        assert not result.executed, "external action must not execute in MVP"
        decision = result.decision
        self._turn_capability = Capability.TOOL_ACTION_REQUEST.value
        self._turn_route = "safety_gate"
        self._turn_safety = (
            f"{decision.risk.value}:blocked" if decision is not None else "blocked"
        )
        self._turn_tool_name = match.tool_name
        self._turn_tool_ok = None  # requested but never executed
        response = self._EXTERNAL_ACTION_RESPONSES[match.tool_name]
        return self._complete_conv(
            state, f"conv:external_action_blocked_{match.tool_name}", response
        )

    # The "tôi nên làm task nào trước" shape has no existing clarification lane, so its
    # payload-less form is answered by the bounded responder's ask-for-tasks. The other
    # payload-less checklist/prioritization forms are owned by the existing P2 lanes.
    _RE_P8A_WHICH_TASK_FIRST = re.compile(
        r'^(?:tôi|mình)\s+nên\s+làm\s+task\s+nào\s+trước\b', re.IGNORECASE,
    )

    def _maybe_handle_capability_response(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-8A: response-only capability requests → bounded LLMResponder.

        Translation/explanation are owned fully by this lane. Checklist/prioritization/
        rewrite/summary answer here only when a payload is present, so every existing
        payload-less clarification contract (P2 lanes, acceptance dataset) is preserved.
        The responder receives ONLY the user text and extracted payload — never memory,
        tools, or runtime state — and its output never overrides a deterministic answer
        (those lanes all run before this one).
        """
        match = self._capability_router.classify(user_message)
        capability = match.capability
        if capability in (Capability.TOOL_ACTION_REQUEST, Capability.UNKNOWN):
            return None
        if capability in (Capability.CHECKLIST, Capability.PRIORITIZATION) and not match.payload:
            if not (
                capability is Capability.PRIORITIZATION
                and self._RE_P8A_WHICH_TASK_FIRST.match(user_message.strip())
            ):
                return None  # existing clarification lanes own these forms
        response: LLMResponse = self._bounded_responder.respond(
            LLMResponseRequest(
                capability=capability,
                user_text=user_message.strip(),
                context={"payload": match.payload} if match.payload else None,
            )
        )
        self._turn_capability = capability.value
        self._turn_route = "bounded_responder"
        self._turn_safety = f"{ActionRisk.READ_ONLY.value}:allowed"
        return self._complete_conv(
            state, f"conv:capability_{capability.value}", response.text
        )

    def _maybe_handle_llm_forbidden_limitation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K xfail-burndown P4: full plan / translation / technical-explanation requests
        cannot be answered without ``LLMResponder`` (forbidden in this MVP). Return a truthful
        current-limitation reply with a bounded next step — NEVER a fabricated plan/answer,
        NEVER a model/provider call. Narrow patterns only, so the general LLM-explanation lane
        ("giải thích AI là gì?") and the responder translation path are untouched."""
        text = user_message.strip()
        if _RE_P4_PLANNING.search(text):
            return self._complete_conv(
                state, "conv:p4_planning_limitation",
                self._response_composer.compose_planning_limitation(),
            )
        if _RE_P4_TRANSLATION.match(text):
            return self._complete_conv(
                state, "conv:p4_translation_limitation",
                self._response_composer.compose_translation_limitation(),
            )
        if _RE_P4_TECHNICAL_DESIGN.search(text) or _is_p4_technical_components_request(text):
            return self._complete_conv(
                state, "conv:p4_technical_limitation",
                self._response_composer.compose_technical_limitation(),
            )
        return None

    def _maybe_handle_memory_edge(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K xfail-burndown P3: bounded memory-edge turns (goal-read variant, imperative
        remember, vague forget, disable-memory-for-turn, assumption/provenance query).

        All are deterministic and truthful: vague forget NEVER deletes (asks which memory),
        the assumption query states the current-MVP limitation instead of faking a
        provenance audit, and disable-for-turn neither stores nor deletes anything.
        """
        text = user_message.strip()

        # memory_004: vague "quên thông tin đó" — clarify, never delete arbitrary memory.
        if _RE_VAGUE_FORGET.match(text):
            return self._complete_conv(
                state, "conv:memory_vague_forget_clarify",
                self._response_composer.compose_vague_forget_clarification(),
            )

        # memory_005: per-turn memory suppression — acknowledge, no store, no delete.
        if _RE_DISABLE_MEMORY_TURN.match(text):
            return self._complete_conv(
                state, "conv:memory_disable_for_turn",
                self._response_composer.compose_disable_memory_for_turn(),
            )

        # memory_006: assumption/provenance query — honest current-MVP limitation.
        if _RE_ASSUMPTION_QUERY.match(text):
            return self._complete_conv(
                state, "conv:memory_assumption_limitation",
                self._response_composer.compose_assumption_query_limitation(),
            )

        # memory_002: "Bạn biết mục tiêu hiện tại của tôi (là gì) không?" — goal-read.
        if _RE_GOAL_CONFIRM_Q.match(text):
            snap = collect_profile_snapshot(self._store)
            if snap.goals:
                answer = (
                    "Theo thông tin bạn cung cấp, mục tiêu hiện tại của bạn là: "
                    + ", ".join(snap.goals) + "."
                )
            else:
                answer = "Mình chưa có thông tin xác nhận về mục tiêu hiện tại của bạn."
            return self._complete_conv(state, "conv:memory_goal_confirm", answer)

        # memory_003: "Hãy nhớ rằng <content>" — imperative confirmed write.
        m = _RE_IMPERATIVE_REMEMBER.match(text)
        if m:
            content = re.sub(r"\s+", " ", m.group(1).strip())
            tokens = content.rstrip("?？ ").split()
            if not tokens or tokens[-1].lower() in ("gì", "gi") or tokens[-1] == "ai":
                return None  # a question, not a fact to store
            # Recognized facts ("hãy nhớ rằng tôi thích X") flow through the normal
            # memory-write handlers; only an otherwise-unhandled activity is stored as a
            # goal below.
            write_result = self._run_memory_write_pipeline(content, state)
            if write_result is not None:
                return write_result
            value = re.sub(
                r'^(?:tôi|mình)\s+(?:đang\s+|sẽ\s+|hiện\s+đang\s+)?', '', content
            ).strip() or content
            candidate = AutoProfileCandidate(
                relation="goal", value=value, original_text=text,
            )
            if goal_already_active(value, self._store):
                return self._complete_conv(
                    state, "conv:memory_imperative_remember_saved",
                    f"Đã ghi nhớ và lưu lại: {value}.",
                )
            if not save_auto_profile_fact(candidate, self._store, state.session_id):
                return None
            self._confirmed_profile_fact_count += 1
            self._last_memory_write_kind = "goal"
            return self._complete_conv(
                state, "conv:memory_imperative_remember_saved",
                f"Đã ghi nhớ và lưu lại: {value}.",
            )

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
        # P0-7K-FIX8-R1 D: while a delete is pending, accept the broader confirmation set
        # (bare "ok"/"yes"/"đồng ý"/"xác nhận"). The strict detector still guards the
        # no-pending stray-confirmation lane, so a random "ok" elsewhere never claims a wipe.
        if detect_delete_all_confirmation_pending(text):
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
        # P0-7K-HOTFIX1 F: answer feedback ("bạn trả lời sai rồi", "bạn phải trả lời
        # là ...") — never write memory; re-answer the last query if we can, else clarify.
        if detect_answer_feedback(user_message.strip()):
            corrected: str | None = None
            if self._last_answered_query is not None:
                corrected = answer_profile_query(self._last_answered_query, self._store)
            return self._complete_conv(
                state, "conv:answer_feedback_repair",
                build_answer_feedback_repair(corrected),
            )
        # P0-7K-HOTFIX1-FIX1 B: a generic "bạn không nhớ à/sao?" reminder — never write,
        # never fall to the generic MVP response; re-answer the last query if resolvable,
        # else offer a targeted clarification. Anchored so a goal challenge like "tôi vẫn
        # muốn làm ML bạn không nhớ à" is left to the goal-reminder path.
        if detect_generic_reminder(user_message.strip()):
            reminder_answer: str | None = None
            if self._last_answered_query is not None:
                reminder_answer = answer_profile_query(
                    self._last_answered_query, self._store
                )
            return self._complete_conv(
                state, "conv:generic_reminder_repair",
                build_generic_reminder_repair(reminder_answer),
            )
        if detect_repair_intent(user_message.strip()):
            self._pending_repair_choice = True
            return self._complete_conv(
                state, "conv:repair_clarify", build_repair_clarification()
            )
        return None

    def _maybe_handle_repair_choice(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX8 L: resolve the repair-choice prompt. A bare choice ("quan hệ") after
        the "... sửa phần nào?" question asks a bounded follow-up instead of falling back."""
        if not self._pending_repair_choice:
            return None
        # One-shot: the pending choice is consumed this turn whether or not it matches, so a
        # stale flag never mis-fires on a later unrelated "quan hệ".
        self._pending_repair_choice = False
        choice = re.sub(r"\s+", " ", user_message.strip().lower()).strip(" .!?？")
        prompts = {
            "quan hệ": 'Bạn muốn sửa quan hệ nào? Ví dụ: "tôi thích Quý", "Quý thích tôi", '
                       'hoặc "tôi và Quý thích nhau".',
            "sở thích": "Bạn muốn sửa sở thích nào? Hãy nói rõ giá trị đúng, "
                        'ví dụ: "tôi thích ML".',
            "kỹ năng": "Bạn muốn sửa kỹ năng nào? Hãy nói rõ giá trị đúng, "
                       'ví dụ: "tôi biết Python".',
            "mục tiêu": "Bạn muốn sửa mục tiêu nào? Hãy nói rõ giá trị đúng, "
                        'ví dụ: "tôi muốn làm LLM".',
            "tên": 'Bạn muốn sửa tên thành gì? Hãy nói rõ, ví dụ: "tên tôi là Bắc".',
        }
        prompt = prompts.get(choice)
        if prompt is None:
            return None
        self._pending_repair_choice = False
        return self._complete_conv(state, "conv:repair_choice_clarify", prompt)

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

    def _maybe_handle_profile_feedback_no_write(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX5A: acknowledge obvious answer feedback without writing memory."""
        if not _RE_PROFILE_FEEDBACK_NO_WRITE.search(user_message.strip()):
            return None
        self._last_memory_write_kind = None
        return self._complete_conv(
            state, "conv:profile_feedback_no_write", _PROFILE_FEEDBACK_NO_WRITE_RESPONSE
        )

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

        # P0-7K-HOTFIX1-FIX1 A: "tôi không thích <người> nữa" with no active positive
        # affection — record negative-affection evidence so the follow-up yes/no answers
        # "no" (not unknown). The WITH-prior case is handled earlier by the affection
        # REMOVE kernel; this branch only fires when nothing was there to remove.
        if intent.category == "affection_negative":
            value = intent.value or ""
            if not save_negative_affection_fact(
                value, self._store, state.session_id,
                original_text=user_message.strip(),
            ):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:affection_negative_saved",
                f"Mình hiểu. Hiện tại bạn không còn thích/quan tâm {value}.",
            )

        # P0-7G / P0-7K-HOTFIX1 D: user-reported external affection, positive or negative
        # ("Quý (cũng/vẫn) thích tôi", "Quý không thích tôi").
        if intent.category in ("external_affection", "external_affection_negative"):
            return self._handle_external_affection(
                intent, user_message, state,
                negated=(intent.category == "external_affection_negative"),
            )

        # P0-7K-FIX6-LITE B: "tôi muốn cưới <người>" — a marry intention stored distinctly
        # (never surfaced by the general "muốn làm gì?" goal query).
        if intent.category == "wants_to_marry":
            person = intent.value or ""
            candidate = AutoProfileCandidate(
                relation="wants_to_marry", value=person,
                original_text=user_message.strip(),
            )
            if not save_auto_profile_fact(candidate, self._store, state.session_id):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:wants_to_marry_saved",
                f"Đã nhớ là bạn muốn cưới {person}.",
            )

        # P0-7K-FIX7-LITE C: "tôi muốn ăn <món>" — a current eating desire stored as weak
        # preference evidence (relation wants_to_eat), kept out of the general goal set.
        if intent.category == "wants_to_eat":
            food = intent.value or ""
            candidate = AutoProfileCandidate(
                relation="wants_to_eat", value=food, original_text=user_message.strip(),
            )
            if not save_auto_profile_fact(candidate, self._store, state.session_id):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:wants_to_eat_saved",
                f"Đã nhớ là hiện tại bạn muốn ăn {food}.",
            )

        # P0-7K-FIX6-LITE C: "tôi muốn học <chủ đề>" — an intention to learn, stored as an
        # action goal ("học <topic>") so it appears in "muốn làm gì?", but acknowledged as
        # an intention (never "đang học", which is a current-activity fact).
        if intent.category == "wants_to_learn":
            topic = intent.value or ""
            goal_value = f"học {topic}"
            if goal_already_active(goal_value, self._store):
                return self._complete_conv(
                    state, "conv:wants_to_learn_saved",
                    f"Đã nhớ là bạn muốn học {topic}.",
                )
            candidate = AutoProfileCandidate(
                relation="goal", value=goal_value, original_text=user_message.strip(),
            )
            if not save_auto_profile_fact(candidate, self._store, state.session_id):
                return None
            self._confirmed_profile_fact_count += 1
            self._last_memory_write_kind = "goal"
            return self._complete_conv(
                state, "conv:wants_to_learn_saved",
                f"Đã nhớ là bạn muốn học {topic}.",
            )

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

    def _maybe_handle_temporal_today(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX7-LITE D / P0-7K-FIX8 A: today-scoped intention, understood in prefix OR
        suffix position and across intention verbs (muốn/sẽ/định/dự định). Not a scheduler.

        The "hôm nay" token is stripped from the stored plan so a dirty generic goal
        ("làm LLM hôm nay") is never persisted — only the clean plan ("làm LLM")."""
        text = user_message.strip()
        if "hôm nay" not in text.lower():
            return None
        m = _RE_FIX8_TODAY_REMOVE.match(text)
        if m:
            plan = self._fix8_clean_today_plan(m.group(1))
            if plan and not self._fix8_is_query_tail(plan):
                removed = delete_temporal_today_fact(plan, self._store)
                if removed is not None:
                    return self._complete_conv(
                        state, "conv:temporal_today_removed",
                        f"Đã bỏ kế hoạch hôm nay: {removed}.",
                    )
                return self._complete_conv(
                    state, "conv:temporal_today_remove_noop",
                    f"Hôm nay mình chưa thấy kế hoạch {plan} nào để bỏ.",
                )
        m = _RE_FIX8_TODAY_WRITE.match(text)
        if m:
            plan = self._fix8_clean_today_plan(m.group(1))
            # A trailing question pronoun ("làm gì") is a query, already answered above.
            if not plan or self._fix8_is_query_tail(plan):
                return None
            if not save_temporal_today_fact(
                plan, self._store, state.session_id, original_text=text
            ):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:temporal_today_saved",
                f"Đã nhớ kế hoạch hôm nay của bạn: {plan}.",
            )
        return None

    @staticmethod
    def _fix8_clean_today_plan(raw: str) -> str:
        """Strip a leading/trailing 'hôm nay' and a trailing 'nữa' from a plan phrase."""
        cleaned = re.sub(r"\s+", " ", raw.strip())
        cleaned = re.sub(r"(?:^hôm\s+nay\s+|\s+hôm\s+nay\b)", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+nữa\b", "", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip(" .!?？")

    @staticmethod
    def _fix8_is_query_tail(plan: str) -> bool:
        """True if the plan ends in a question pronoun ("làm gì"/"làm ai") — a query, not a
        write. "ai" is checked case-sensitively so the tech token "AI" still writes."""
        tokens = plan.rstrip("?？ ").split()
        if not tokens:
            return True
        last = tokens[-1]
        return last.lower() in ("gì", "gi") or last == "ai"

    def _maybe_handle_fix8_intention_goal(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX8 C/D: durable intention alias ("tôi định làm Chatbox") and its
        retraction ("tôi không định/muốn làm Agent nữa"). "hôm nay" forms are owned by the
        temporal lane and are skipped here."""
        text = user_message.strip()
        if "hôm nay" in text.lower():
            return None
        # A compound goal-switch ("... không muốn build LLM NỮA TÔI MUỐN build AI Agent") is
        # owned by the existing goal pipeline (remove + add in one turn); do not intercept it.
        if re.search(r'\bnữa\s+(?:tôi|mình)\s+(?:muốn|định|sẽ|dự\s+định)\b', text, re.IGNORECASE):
            return None
        m = _RE_FIX8_INTENT_REMOVE.match(text)
        if m:
            plan = re.sub(r"\s+", " ", m.group(1).strip()).strip(" .!?？")
            if not plan or self._fix8_is_query_tail(plan):
                return None
            if not save_negative_goal_fact(
                plan, self._store, state.session_id, original_text=text
            ):
                return None
            self._confirmed_profile_fact_count += 1
            self._last_memory_write_kind = None
            return self._complete_conv(
                state, "conv:fix8_intention_retracted",
                f"Đã ghi nhận: hiện tại bạn không còn muốn {plan}.",
            )
        m = _RE_FIX8_INTENT_WRITE.match(text)
        if m:
            plan = re.sub(r"\s+", " ", m.group(1).strip()).strip(" .!?？")
            if not plan or self._fix8_is_query_tail(plan):
                return None
            if not save_intention_goal_fact(
                plan, self._store, state.session_id, original_text=text
            ):
                return None
            self._confirmed_profile_fact_count += 1
            self._last_memory_write_kind = "goal"
            return self._complete_conv(
                state, "conv:fix8_intention_saved",
                f"Đã nhớ là bạn định {plan}.",
            )
        return None

    @staticmethod
    def _fix8_person_match(needle: str, haystack: list[str]) -> str | None:
        """Return the stored spelling of a person from ``haystack`` matching ``needle``
        case-insensitively, else None."""
        key = re.sub(r"\s+", " ", needle.strip().lower())
        for item in haystack:
            if re.sub(r"\s+", " ", item.strip().lower()) == key:
                return item
        return None

    def _maybe_handle_fix8_embedded_correction(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX8 F: an embedded self-correction ("tôi nói là tôi định làm CÓ NGHĨA LÀ
        tôi muốn làm Chatbox") — extract only the trailing intended fact, never the meta
        wrapper, and record it as an intention."""
        text = user_message.strip()
        m = re.search(
            r'(?:có\s+nghĩa\s+là|nghĩa\s+là|ý\s+(?:tôi\s+)?là)\s+(?:tôi|mình)\s+'
            r'(?:muốn|định|sẽ|dự\s+định)\s+((?:làm|build)\s+.+?)\s*[.!?]*\s*$',
            text, flags=re.IGNORECASE,
        )
        if m is None:
            return None
        plan = re.sub(r"\s+", " ", m.group(1).strip()).strip(" .!?？")
        if not plan or self._fix8_is_query_tail(plan):
            return None
        if not save_intention_goal_fact(
            plan, self._store, state.session_id, original_text=text
        ):
            return None
        self._confirmed_profile_fact_count += 1
        self._last_memory_write_kind = "goal"
        return self._complete_conv(
            state, "conv:fix8_embedded_correction",
            f"Mình hiểu. Mình sẽ ghi nhận {plan} là việc bạn muốn/định làm.",
        )

    def _maybe_handle_fix8_compound_relation(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX8 I: a compound relation write joining an incoming clause (person→USER)
        and an outgoing clause (USER→person) with "và" ("may cũng thích tôi và tôi cũng
        thích may"). Stores both edges; never stores "tôi" as a liked person."""
        m = _RE_FIX8_COMPOUND_RELATION.match(user_message.strip())
        if m is None:
            return None
        clauses = [m.group(1).strip(), m.group(2).strip()]
        admirer: str | None = None
        liked: str | None = None
        for clause in clauses:
            mi = _RE_FIX8_INCOMING_CLAUSE.match(clause)
            if mi is not None:
                # R1 B: the subject group can greedily swallow a discourse modifier
                # ("may cũng"); canonicalize so only the real name is stored.
                admirer = canonical_person_name(mi.group(1).strip())
                continue
            mo = _RE_FIX8_OUTGOING_CLAUSE.match(clause)
            if mo is not None:
                liked = canonical_person_name(mo.group(1).strip())
                continue
            # An unrecognized clause → not a clean compound relation; let other lanes try.
            return None
        if admirer is None or liked is None:
            return None
        if admirer.lower() in _EXTERNAL_AFFECTION_SELF_WORDS or liked.lower() in _EXTERNAL_AFFECTION_SELF_WORDS:
            return None
        saved = False
        if save_external_affection_fact(
            admirer, self._store, state.session_id, original_text=user_message.strip()
        ):
            self._confirmed_profile_fact_count += 1
            saved = True
        if save_affection_fact(
            liked, self._store, state.session_id, original_text=user_message.strip()
        ):
            self._confirmed_profile_fact_count += 1
            saved = True
        if not saved:
            return None
        return self._complete_conv(
            state, "conv:fix8_compound_relation",
            f"Đã nhớ: {admirer} thích bạn, và bạn cũng thích {liked}.",
        )

    def _maybe_handle_fix8_continuation_admirer(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX8 J: after an incoming-affection query ("ai đang thích tôi"), a bare
        continuation ("cả may nữa") adds one more admirer. Only fires when the previous
        answered query was the incoming-affection set.

        P0-7K-FIX8-FIX1: WITHOUT that context, the same shape ("cả may nữa"/"may
        nữa"/"thêm may nữa") is genuinely ambiguous — it could mean "X likes me", "I like
        X", or something else entirely. Ask a named, context-specific clarification instead
        of the generic continuation prompt, and never store an admirer without context."""
        m = _RE_FIX8_CONTINUATION_ADMIRER.match(user_message.strip())
        if m is None:
            return None
        admirer = re.sub(r"\s+", " ", m.group(1).strip())
        # "gì"/"ai" are question words ("gì nữa?", "ai nữa?"), not a name — leave those to
        # the existing goal/preference follow-up lane. "ai" is checked case-sensitively so
        # the tech token "AI" ("cả AI nữa") is still treated as a real admirer candidate.
        if not admirer or admirer.lower() in _EXTERNAL_AFFECTION_SELF_WORDS:
            return None
        if admirer.lower() in ("gì", "gi") or admirer == "ai":
            return None
        # R1 B: strip any residual discourse modifier ("may cũng") before storing.
        admirer = canonical_person_name(admirer)
        if not admirer or admirer.lower() in _EXTERNAL_AFFECTION_SELF_WORDS:
            return None
        if self._last_profile_query_kind != "incoming_affection_set":
            return self._complete_conv(
                state, "conv:fix8_continuation_no_context",
                f'Mình chưa có ngữ cảnh rõ cho "{admirer} nữa". Bạn muốn nói cụ thể là '
                f"{admirer} thích bạn, bạn thích {admirer}, hay {admirer} cũng thuộc danh "
                "sách nào?",
            )
        if not save_external_affection_fact(
            admirer, self._store, state.session_id, original_text=user_message.strip()
        ):
            return None
        self._confirmed_profile_fact_count += 1
        return self._complete_conv(
            state, "conv:fix8_continuation_admirer",
            f"Đã nhớ thêm: {admirer} cũng thích bạn.",
        )

    def _maybe_handle_fix8_relation_queries(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX8 E/G/H/K/M/N: bounded factual relation/temporal queries that otherwise
        fall to the generic fallback. No inference beyond stored edges."""
        text = user_message.strip()

        # N: future-date plan query — only "hôm nay" is supported.
        m = _RE_FIX8_FUTURE_DATE_Q.match(text)
        if m is not None:
            when = re.sub(r"\s+", " ", m.group(1).strip().lower())
            return self._complete_conv(
                state, "conv:fix8_future_date_limit",
                f'Hiện tại mình mới hỗ trợ kế hoạch "hôm nay", chưa hỗ trợ kế hoạch cho {when}.',
            )

        # E: yes/no about today's plan (tolerant of the "cps" typo for "có").
        m = _RE_FIX8_TODAY_YESNO.match(text)
        if m is not None:
            plan = self._fix8_clean_today_plan(m.group(1))
            snap = collect_profile_snapshot(self._store)
            target = set(re.sub(r"\s+", " ", plan.lower()).split())
            for intent in snap.today_intentions:
                key = re.sub(r"^(?:làm|build)\s+", "", intent.lower())
                if target and (target <= set(key.split()) or set(key.split()) <= target):
                    return self._complete_conv(
                        state, "conv:fix8_today_yesno_yes",
                        f"Có, hôm nay bạn muốn {intent}.",
                    )
            return self._complete_conv(
                state, "conv:fix8_today_yesno_no",
                f"Hôm nay mình chưa thấy kế hoạch {plan} nào của bạn.",
            )

        # M: relationship advice — bounded limitation + known memory summary (NOT a factual
        # mutual answer). Checked before the mutual query ("nên" marks advice).
        m = _RE_FIX8_RELATION_ADVICE.match(text)
        if m is not None:
            person = re.sub(r"\s+", " ", m.group(1).strip())
            snap = collect_profile_snapshot(self._store)
            liked = self._fix8_person_match(person, snap.affections)
            admired = self._fix8_person_match(person, snap.external_affections)
            display = liked or admired or person
            summary = self._fix8_relation_summary(display, bool(liked), bool(admired))
            return self._complete_conv(
                state, "conv:fix8_relationship_advice",
                "Mình chưa có module tư vấn quan hệ trong MVP rule-based. " + summary,
            )

        # H: factual mutual-affection query (symmetric in USER/person order — R1 A).
        m = _RE_FIX8_MUTUAL_LIKE.match(text)
        if m is not None:
            raw_person = m.group("a") or m.group("b") or ""
            person = canonical_person_name(re.sub(r"\s+", " ", raw_person.strip()))
            snap = collect_profile_snapshot(self._store)
            liked = self._fix8_person_match(person, snap.affections)
            admired = self._fix8_person_match(person, snap.external_affections)
            display = liked or admired or person
            if liked and admired:
                return self._complete_conv(
                    state, "conv:fix8_mutual_yes",
                    f"Có, theo thông tin hiện tại: bạn thích {display} và {display} "
                    "cũng thích bạn.",
                )
            if liked and not admired:
                return self._complete_conv(
                    state, "conv:fix8_mutual_one_side",
                    f"Bạn thích {display}, nhưng mình chưa thấy thông tin rằng {display} "
                    "thích bạn.",
                )
            if admired and not liked:
                return self._complete_conv(
                    state, "conv:fix8_mutual_one_side",
                    f"{display} thích bạn, nhưng mình chưa thấy thông tin rằng bạn thích "
                    f"{display}.",
                )
            return self._complete_conv(
                state, "conv:fix8_mutual_unknown",
                "Mình chưa thấy thông tin về việc này.",
            )

        # K: double affection query ("ai đang thích tôi và tôi đang thích ai?").
        if _RE_FIX8_DOUBLE_AFFECTION_Q.match(text) is not None:
            snap = collect_profile_snapshot(self._store)
            incoming = list(snap.external_affections)
            outgoing = list(snap.affections)
            in_text = ", ".join(incoming) if incoming else "chưa có ai"
            out_text = ", ".join(outgoing) if outgoing else "chưa có ai"
            return self._complete_conv(
                state, "conv:fix8_double_affection",
                f"Người đang thích bạn: {in_text}.\nNgười bạn đang thích: {out_text}.",
            )

        # G: historical preference query ("tôi có từng thích ăn kem không?").
        m = _RE_FIX8_HISTORICAL_LIKE.match(text)
        if m is not None:
            obj = re.sub(r"\s+", " ", m.group(1).strip().rstrip("?？"))
            snap = collect_profile_snapshot(self._store)
            actives = snap.preferences_personal + snap.preferences_professional
            if self._fix8_pref_contains(obj, actives):
                return self._complete_conv(
                    state, "conv:fix8_historical_active",
                    f"Có, hiện tại bạn vẫn thích {obj}.",
                )
            if self._fix8_pref_contains(obj, snap.dislikes):
                return self._complete_conv(
                    state, "conv:fix8_historical_retracted",
                    f"Có, trước đây bạn từng thích {obj}, nhưng hiện tại bạn không "
                    f"thích {obj}.",
                )
            return self._complete_conv(
                state, "conv:fix8_historical_unknown",
                f"Mình chưa thấy thông tin rằng bạn từng thích {obj}.",
            )

        return None

    @staticmethod
    def _fix8_pref_contains(needle: str, prefs: list[str]) -> bool:
        """Token-subset match of a preference object against a stored preference list, so
        "ăn kem" matches a stored "kem"/"ăn kem" and vice versa."""
        target = set(re.sub(r"\s+", " ", needle.lower()).split())
        if not target:
            return False
        for pref in prefs:
            tokens = set(re.sub(r"\s+", " ", pref.lower()).split())
            if target <= tokens or tokens <= target:
                return True
        return False

    @staticmethod
    def _fix8_relation_summary(person: str, liked: bool, admired: bool) -> str:
        if liked and admired:
            return (
                f"Theo memory hiện tại, bạn thích {person} và {person} cũng thích bạn "
                "theo thông tin bạn cung cấp."
            )
        if liked:
            return f"Theo memory hiện tại, bạn thích {person}."
        if admired:
            return (
                f"Theo memory hiện tại, {person} thích bạn theo thông tin bạn cung cấp."
            )
        return f"Theo memory hiện tại, mình chưa thấy quan hệ tình cảm nào với {person}."

    def _maybe_handle_stop_eat(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX7-LITE C: "tôi không muốn ăn <món> nữa" — drop the eating desire."""
        m = _RE_STOP_EAT.match(user_message.strip())
        if m is None:
            return None
        food = re.sub(r"\s+", " ", m.group(1).strip())
        tokens = food.rstrip("?？ ").split()
        if not tokens or tokens[-1].lower() in ("gì", "gi"):
            return None
        removed = delete_wants_to_eat_fact(food, self._store)
        if removed is not None:
            return self._complete_conv(
                state, "conv:wants_to_eat_removed",
                f"Đã bỏ, hiện tại bạn không còn muốn ăn {removed}.",
            )
        return self._complete_conv(
            state, "conv:wants_to_eat_remove_noop",
            f"Mình chưa thấy bạn đang muốn ăn {food}.",
        )

    def _maybe_handle_coordinated_external_affection(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX6-LITE G: "may và quý (đều) thích tôi" → save one person→USER affection
        edge per subject. Fires only for ≥2 subjects whose object resolves to the user."""
        m = _RE_COORDINATED_EXTERNAL_AFFECTION.match(user_message.strip())
        if m is None:
            return None
        obj = m.group(2).strip()
        snap = collect_profile_snapshot(self._store)
        obj_is_user = (
            obj.lower() in _EXTERNAL_AFFECTION_SELF_WORDS
            or (snap.name is not None and self._norm(obj) == self._norm(snap.name))
            or any(self._norm(obj) == self._norm(n) for n in snap.previous_names)
        )
        if not obj_is_user:
            return None
        subjects = [
            s.strip() for s in re.split(r'\s*,\s*|\s+và\s+', m.group(1).strip()) if s.strip()
        ]
        # Any admirer that is itself a self word is not a real third-party subject.
        subjects = [s for s in subjects if s.lower() not in _EXTERNAL_AFFECTION_SELF_WORDS]
        if len(subjects) < 2:
            return None
        saved: list[str] = []
        for subj in subjects:
            if save_external_affection_fact(
                subj, self._store, state.session_id, original_text=user_message.strip()
            ):
                saved.append(subj)
        if not saved:
            return None
        self._confirmed_profile_fact_count += len(saved)
        joined = " và ".join(saved) if len(saved) <= 2 else (
            ", ".join(saved[:-1]) + " và " + saved[-1]
        )
        return self._complete_conv(
            state, "conv:coordinated_external_affection_saved",
            f"Đã nhớ theo thông tin bạn cung cấp: {joined} thích bạn.",
        )

    def _maybe_handle_alias_affection_statement(
        self, user_message: str, state: AgentState
    ) -> AgentState | None:
        """P0-7K-FIX5C-LITE G: "bây giờ bắc thích quý" where "bắc" is an old/current self
        alias → rewrite to "tôi thích quý" and re-dispatch so it becomes a self-affection
        write (reusing the person-vs-preference disambiguation). Bare self-word subjects
        ("tôi thích quý") already flow through the normal pipeline, so they are left alone."""
        m = _RE_ALIAS_AFFECTION_STMT.match(user_message.strip())
        if m is None:
            return None
        subject = m.group(1).strip()
        verb = m.group(2).strip()
        obj = m.group(3).strip()
        if subject.lower() in _EXTERNAL_AFFECTION_SELF_WORDS or obj.lower() in ("ai",):
            return None
        snap = collect_profile_snapshot(self._store)
        subject_is_user = (
            (snap.name is not None and self._norm(subject) == self._norm(snap.name))
            or any(self._norm(subject) == self._norm(n) for n in snap.previous_names)
        )
        if not subject_is_user:
            return None
        # The object must not itself be the user ("bắc thích BB" is not a self-affection).
        obj_is_user = (
            obj.lower() in _EXTERNAL_AFFECTION_SELF_WORDS
            or (snap.name is not None and self._norm(obj) == self._norm(snap.name))
            or any(self._norm(obj) == self._norm(n) for n in snap.previous_names)
        )
        if obj_is_user:
            return None
        return self._run_memory_write_pipeline(f"tôi {verb} {obj}", state)

    def _handle_external_affection(
        self, intent: SemanticProfileIntent, user_message: str, state: AgentState,
        *, negated: bool = False,
    ) -> AgentState | None:
        """P0-7G / P0-7K-HOTFIX1 D: save a user-reported external affection fact (positive
        or negative) only when its object is the current user (a self word, the saved
        name, or an old-name alias). Otherwise fall through."""
        admirer = intent.value or ""
        obj = (intent.relation_label or "").strip()
        snap = collect_profile_snapshot(self._store)
        obj_is_user = (
            obj.lower() in _EXTERNAL_AFFECTION_SELF_WORDS
            or (snap.name is not None and self._norm(obj) == self._norm(snap.name))
            or any(self._norm(obj) == self._norm(n) for n in snap.previous_names)
        )
        if not obj_is_user:
            # P0-7G-FIX1: unrelated third-party affection ("Quý thích Nam") — narrow
            # safe/no-save reply instead of the generic rule-based fallback.
            return self._complete_conv(
                state, "conv:unrelated_external_affection",
                build_unrelated_external_affection_response(admirer, obj),
            )
        if negated:
            if not save_negative_external_affection_fact(
                admirer, self._store, state.session_id, original_text=user_message.strip()
            ):
                return None
            self._confirmed_profile_fact_count += 1
            return self._complete_conv(
                state, "conv:external_affection_negative_saved",
                f"Đã ghi nhận theo thông tin bạn cung cấp: {admirer} không thích bạn.",
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
