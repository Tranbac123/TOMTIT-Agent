# SECURITY_DEBT.md — TOMTIT-Agent

> **Đây là tài liệu GHI NỢ, KHÔNG phải spec thực thi.** Không item nào trong file này
> được Claude Code tự khởi động. Mỗi item có **trigger** — điều kiện khiến nó chuyển từ
> "ghi để đó" sang "phải làm". Chừng nào trigger chưa bật, item ở yên.
>
> Lý do tồn tại: ghi lại đánh giá an toàn để nó không bị quên đúng lúc cần — KHÔNG phải
> để biện minh cho việc xây security layer trước khi MVP chạy. Bề mặt tấn công của một
> agent local / single-user / rule-based parser / tool read-only là gần bằng không.
>
> **Cập nhật:** 2026-06. Trạng thái repo: P0/P1/P2 đóng, P3 ready for execution.

---

## 0. Nguyên tắc

- **Không build phòng thủ cho mối đe dọa chưa tồn tại.** Mỗi mục chỉ làm khi trigger bật.
- **"Có interface" ≠ "an toàn".** Một cơ chế tồn tại trong code không có nghĩa nó thật sự
  chặn trong runtime — phải có test chứng minh.
- File này đánh giá theo _khi nào cần_, không _liệt kê cho đủ_.

---

## 1. Lớp Input Safety

### Trạng thái hiện tại: gần như KHÔNG tồn tại

| Cơ chế                                       | Trạng thái                                  |
| -------------------------------------------- | ------------------------------------------- |
| Prompt injection detection                   | **Không có**                                |
| Phát hiện yêu cầu vượt quyền ở input         | **Không có** (chỉ chặn muộn ở ToolExecutor) |
| Nội dung nguy hiểm / manipulation classifier | **Không có**                                |
| Input guardrail bất kỳ                       | **Không có**                                |

### Phòng thủ tình cờ (KHÔNG phải cơ chế có chủ đích)

`RuleBasedIntentParser` chỉ match tiền tố `Tính/Đọc ghi chú/Lưu|Ghi/Tìm`. Mọi input
khác → `UNKNOWN` → không tạo plan → không execute. Prompt injection kiểu "ignore previous
instructions" **không có đường tác động** vì parser không diễn giải ngôn ngữ tự do.

> ⚠️ **Đây là phòng thủ do kiến trúc, không phải cơ chế an toàn.** Nó biến mất ngay khi
> thêm LLM vào pipeline parsing.

### Triggers — khi nào Input Safety chuyển thành PHẢI LÀM

| Trigger                                                                           | Item phải làm                                                                                                                                    |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Thêm `LLMIntentParser` / `HybridParser`** (post-MVP)                            | **BẮT BUỘC** prompt-injection guard TRƯỚC khi merge LLM parser. Đây là lúc injection có đường vào thật. Không có guard = không merge LLM parser. |
| Agent nhận input từ nguồn không tin cậy (web content, file người khác, API ngoài) | Input sanitization + tách "trusted instruction" vs "untrusted data"                                                                              |
| Multi-user / phục vụ qua mạng                                                     | Authn/authz ở input boundary; rate limiting                                                                                                      |
| Agent xử lý dữ liệu nhạy cảm                                                      | PII/secret scanning ở input                                                                                                                      |

### Khi trigger bật — cần bổ sung gì (phác thảo, KHÔNG implement bây giờ)

- Một `InputGuard` chạy TRƯỚC `IntentParser` trong runtime flow.
- Tách rõ trusted (lệnh user trực tiếp) vs untrusted (nội dung tool/web trả về) — untrusted
  KHÔNG được nâng thành instruction.
- Deterministic rule trước, classifier sau (giữ đúng "code kiểm soát hành vi").

---

## 2. Lớp Execution Safety

### Trạng thái hiện tại: TỒN TẠI THẬT — phần mạnh nhất của hệ thống

| Cơ chế                                         | Trạng thái                                      | Ghi chú                                                                                                                                                                                                                                                      |
| ---------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Single execution gate (`ToolExecutor.execute`) | ✅ Triển khai thật, có test                     | Chỗ duy nhất gọi `tool.fn`. CLAUDE.md + test guard.                                                                                                                                                                                                          |
| `max_steps` giới hạn loop                      | ✅ Triển khai                                   | Chặn loop vô hạn                                                                                                                                                                                                                                             |
| Read-only auto-run                             | ✅ Triển khai                                   | `state.read_only` + check executor                                                                                                                                                                                                                           |
| Intent-unclear → no-execute                    | ✅ (side-effect của state-first)                | Không phải input safety có chủ đích                                                                                                                                                                                                                          |
| PolicyEngine chặn trước execute                | ⚠️ Triển khai — **độ sâu cần verify bằng test** | Cơ chế có; chưa chứng minh MỌI side-effect bị chặn đúng                                                                                                                                                                                                      |
| ApprovalGate cho side-effect                   | ⚠️ Interface + wiring — **cần test chứng minh** | `requires_approval` + `state.approved_tools`; cần test "chưa approve → DENY"                                                                                                                                                                                 |
| Risk classification                            | 🟡 Metadata only                                | `ToolSpec.risk_level/side_effects/mutates_state` có; `risk.py` logic runtime **rỗng**                                                                                                                                                                        |
| retry / timeout                                | 🟡 Metadata only                                | Field có; executor CHƯA thực thi (đóng băng BUILD_SPEC STEP 8)                                                                                                                                                                                               |
| `execution_degraded` → chặn side-effect        | 📝 Field + logic CHƯA làm (QĐ-4)                | Tách khỏi `memory_degraded`: `memory_degraded` chỉ disclose, KHÔNG chặn. `execution_degraded` (block side-effect khi audit/authz/sandbox down) là **field + logic deferred** — KHÔNG thêm field ở P3 vì chưa có consumer. Thêm khi có execution safety thật. |
| Rollback / compensation                        | ❌ Không có                                     | Preview+approve có; UNDO sau khi chạy thì không                                                                                                                                                                                                              |

### Lỗ hổng Execution Safety

1. **Chưa chứng minh ApprovalGate thật sự chặn.** Cơ chế tồn tại, nhưng sau nhiều STEP
   sửa, chưa có test khẳng định "side-effect tool + chưa approve → `tool.fn` KHÔNG chạy".
   Đây là tuyên bố an toàn cốt lõi đang chưa được verify.
2. **`risk_level` là metadata chết** — không có logic runtime đọc nó để phân tầng xử lý.
3. **Không rollback cho irreversible action.** Gửi email sai/xóa file → không undo được.
4. **Approval nhị phân** — chỉ approve/không, chưa phân tầng (low-risk auto, high-risk
   approval mạnh, irreversible chặn mặc định).

### Triggers — khi nào từng item chuyển thành PHẢI LÀM

| Trigger                                                              | Item phải làm                                                                            |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Trước P4-local-demo** (gần — xem §4)                               | **Test chứng minh ApprovalGate chặn** side-effect khi chưa approve. RẺ, đúng đường găng. |
| Thêm tool side-effect THẬT (email/calendar/file-delete/external API) | `risk.py` logic thật; approval phân tầng; preview bắt buộc cho irreversible              |
| Tool irreversible / costly (payment, xóa vĩnh viễn)                  | Rollback/compensation plan; chặn mặc định + approval mạnh                                |
| Production deploy                                                    | Audit log bất biến (event log STEP 7); rate limiting; monitoring                         |

---

## 3. Phân loại tổng: chặn-MVP vs production-debt

**Chặn MVP-local: gần như KHÔNG.**
Agent local, single-user, rule-based parser, tool read-only/note → bề mặt tấn công ~0.
Việc an toàn DUY NHẤT đáng làm gần MVP = test ApprovalGate (§4).

**Production-debt (làm khi trigger bật, KHÔNG phải bây giờ):**

- Prompt-injection guard (trigger: LLM parser)
- `risk.py` logic (trigger: tool side-effect thật)
- Rollback/compensation (trigger: irreversible tool)
- Audit log bất biến (trigger: production)
- Rate limiting, PII scanning, authn/authz (trigger: multi-user/mạng)

---

## 4. Việc an toàn DUY NHẤT đáng làm gần MVP

**Như một GATE trước khi P4-local-demo được DUYỆT** (không phải bây giờ — đang P3), làm một việc:

> **Test (chốt — chỉ dựa `requires_approval`, KHÔNG `mutates_state`):** một tool giả
> `ToolSpec(requires_approval=True)` + chưa có trong `state.approved_tools` → `ToolExecutor.execute`
> trả DENY/ApprovalRequired, `tool.fn` KHÔNG được gọi (spy đếm `fn` chạy = 0).
>
> **KHÔNG dùng `mutates_state=True` làm điều kiện DENY.** Lý do: `write_note` có
> `mutates_state=True, requires_approval=False` — nếu DENY theo `mutates_state` thì `write_note`
> bị chặn → gãy compound demo (mâu thuẫn QĐ-4). `mutates_state` dùng cho read-only/policy
> classification, KHÔNG tự động = cần approval.
>
> Nếu sau này muốn MỌI mutating tool cần approval → đó là **thay đổi policy riêng**; khi đó
> `write_note` phải được approve rõ trong demo (thêm vào `approved_tools`).

Nếu test xanh → lớp Execution Safety vững cho MVP. Nếu đỏ → lỗ hổng thật, vá ngay.
Đây là việc rẻ nhất, đúng đường găng nhất — KHÔNG phải xây input-safety layer.

---

## 5. Điều KHÔNG được làm vì file này

File này KHÔNG cho phép:

- ❌ Khởi động bất kỳ item nào khi trigger chưa bật
- ❌ Xây `InputGuard` / injection detection khi parser còn rule-based
- ❌ Thêm rollback/audit/rate-limit trước khi có tool side-effect thật / production
- ❌ Rời đường găng P2 → P3 → P4 để làm security

Đường găng hiện tại không đổi: **P2-local-client → P3-runtime-wiring → P4-local-demo.**
Security theo trigger, không theo lo lắng.
