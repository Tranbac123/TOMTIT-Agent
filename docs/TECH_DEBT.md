# TECH_DEBT.md

> Ghi các khoản nợ kỹ thuật đã xác minh. Mỗi mục: mức độ, trạng thái, bằng chứng.
> Không phải backlog — chỉ ghi khi có evidence cụ thể.
> Cập nhật khi close hoặc escalate.

---

## TD-1 — `WEB_SEARCH_THEN_SAVE_NOTE` thiếu planner branch

**Mức độ:** Medium
**Trạng thái:** OPEN

**Mô tả:**
`IntentName.WEB_SEARCH_THEN_SAVE_NOTE` được parse và validate slot đầy đủ, nhưng
`IntentPlanner.make_plan()` không có branch tương ứng → rơi `_unknown_plan` → user
nhận "Tôi chưa biết xử lý task này."

**Files liên quan:**
- `agent_core/planning/intent_parser.py` — parse ra đúng intent
- `agent_core/planning/slot_validator.py` — yêu cầu `(query, note_name)`
- `agent_core/planning/intent_planner.py` — thiếu branch `WEB_SEARCH_THEN_SAVE_NOTE`

**Bằng chứng:** `grep WEB_SEARCH_THEN_SAVE_NOTE agent_core/planning/intent_planner.py`
→ no output (verified 2026-06-15).

**Fix cần:** Thêm `_web_search_then_save_note_plan()` vào `IntentPlanner`, tương tự
`_calculate_then_save_note_plan()`. Cần spec + gate trước khi sửa.

---

## TD-2 — Project-context parser có thể bắt nhầm câu trần thuật

**Mức độ:** Low
**Trạng thái:** OPEN

**Mô tả:**
`_PROJECT_QUERY_CUE` dùng alternation `context|ngữ cảnh` (không phân biệt hỏi/trần thuật).
Câu "Dự án cần thêm ngữ cảnh để chạy" (trần thuật kỹ thuật) có thể trigger
`PROJECT_CONTEXT_QUERY` nhầm.

**Root cause:** Rule hiện tại: `^Dự án` AND cue. Thiếu điều kiện phân biệt câu hỏi.

**Fix đề xuất:** Thêm question-cue vào điều kiện: decision-cue AND question-cue
(`nào|gì|ra sao|thế nào|\?`). Cần thêm negative test cho pattern trần thuật.

**Bằng chứng:** Code review `intent_parser.py:_PROJECT_QUERY_CUE` (verified 2026-06-15).
Hiện chỉ có 2 negative test: `"Dự án đang chạy bình thường"` (không có cue) và
`"Tìm thông tin về dự án"` (`^Tìm` win trước). Không có negative test cho trần thuật có cue.

---

## TD-3 — `LIST_NOTES` và `SUMMARIZE_MEMORY` có tool nhưng không có intent tạo plan

**Mức độ:** Low
**Trạng thái:** OPEN

**Mô tả:**
Cả hai tool đăng ký đầy đủ trong registry (`ToolSpec` tồn tại, completeness guard pass),
nhưng không có `IntentName` member nào map đến chúng → planner không bao giờ generate
step dùng hai tool này từ user goal.

Hiện accessible gián tiếp qua `MemoryAgent` trong builtin tools — không phải qua planner.

**Fix cần:** Thêm intent `LIST_NOTES` / `SUMMARIZE_MEMORY` vào `IntentName` + parser branch
+ planner branch. Ngoài scope MVP hiện tại.

---

## TD-4 — `PolicyEngine` không chặn `RiskLevel.CRITICAL`

**Mức độ:** High (safety)
**Trạng thái:** PATCHED — chờ commit

**Mô tả:**
`PolicyEngine.check()` dùng `== RiskLevel.HIGH` thay vì `in (RiskLevel.HIGH, RiskLevel.CRITICAL)`.
`RiskLevel.CRITICAL` tồn tại trong `enums.py` nhưng không bị deny → tool CRITICAL có thể
vượt policy gate và thực thi.

**Bằng chứng:**
- `policy.py:41`: `if tool.risk_level == RiskLevel.HIGH:` (verified 2026-06-15)
- `grep CRITICAL tests/` → 0 kết quả trước patch (verified 2026-06-15)

**Patch đã áp dụng (chưa commit):**
- `policy.py:41`: đổi thành `if tool.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):`
- `tests/test_tools.py`: thêm `test_executor_blocks_critical_risk_tool` — spy `call_count == 0`
- `102 passed` sau patch

**Cần TranBac duyệt commit.**
