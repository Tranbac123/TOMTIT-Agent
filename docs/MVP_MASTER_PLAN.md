# TOMTIT MVP — Master Plan (Agent ↔ Memory integration)

> **Definition of Done — HAI TẦNG (đọc kỹ, đây là điểm từng mâu thuẫn):**
>
> **MVP-local DoD (đích chính, đạt trước):** TOMTIT-Agent chạy end-to-end với
> `LocalMemoryClient` — retrieve `ContextPack` **trước plan**, write memory candidates
> **sau finish**, final answer disclose degraded khi cần. Chứng minh bằng script demo.
> **KHÔNG cần TOMTIT-Memory HTTP server.** Đây là cột mốc "MVP chạy được".
>
> **MVP-remote DoD (integration milestone kế tiếp):** ghép `RemoteMemoryClient` qua
> HTTP với TOMTIT-Memory, `degraded=False`, **runtime không đổi một dòng**. Đây là
> bước tích hợp sau, KHÔNG phải điều kiện chặn của "MVP chạy được".
>
> **Trạng thái xuất phát (đã xác nhận):**
>
> - TOMTIT-Agent: **chưa import được** (4 lỗi P0).
> - TOMTIT-Memory: **có code, chưa có HTTP server chạy được**.
>
> **Nguyên tắc tốc độ:** nhanh = làm đúng thứ tự, KHÔNG bỏ bước. MVP chạy được trước
> bằng `LocalMemoryClient`; remote HTTP là integration milestone kế tiếp.

---

## 1. Critical path — phase ĐẶT TÊN (không dùng số lộn thứ tự)

Thứ tự tuyến tính, một-phase-một-gate. **Tên có nghĩa, không số** — để executor không nhầm.

| Phase                 | Nội dung                                                              | Repo   | Spec                                              |
| --------------------- | --------------------------------------------------------------------- | ------ | ------------------------------------------------- |
| **P0-recovery**       | Sửa 4 lỗi P0 → Agent import được, pytest xanh                         | Agent  | `BUILD_SPEC.md` STEP 1–5                          |
| **P1-contract**       | Chốt `ContextPack` + `MemoryClientProtocol` (một nguồn sự thật)       | Agent  | `SPEC_memory_client.md` §2 + §7b                  |
| **P2-local-client**   | `LocalMemoryClient` bọc `InMemoryStore` + test                        | Agent  | `SPEC_memory_client.md` [MVP-local must]          |
| **P3-runtime-wiring** | retrieve trước plan → inject → write sau finish + degraded disclosure | Agent  | `SPEC_memory_client.md` §5                        |
| **P4-local-demo**     | E2E local: 1 luồng với `LocalMemoryClient`, demo được                 | Agent  | cần viết                                          |
| —                     | **🎯 MVP-local DoD đạt ở đây — dừng được, đi nói chuyện user**        | —      | —                                                 |
| **P5-remote-memory**  | Memory HTTP server (`/retrieve`, `/write`, `/handshake`)              | Memory | cần viết                                          |
| **P6-remote-client**  | `RemoteMemoryClient` + factory binding-at-task-start                  | Agent  | `SPEC_memory_client.md` [Remote integration must] |
| **P7-remote-demo**    | E2E remote: agent ↔ TOMTIT-Memory thật, `degraded=False`              | cả 2   | cần viết                                          |

**Đường găng tuyến tính:**

```
P0-recovery → P1-contract → P2-local-client → P3-runtime-wiring → P4-local-demo
   🎯 MVP-local DoD
       └→ P5-remote-memory → P6-remote-client → P7-remote-demo
              🎯 MVP-remote DoD
```

**Vì sao local-first:** P2 cho một `MemoryClient` chạy được **trước khi** TOMTIT-Memory
có HTTP server. P4 (demo local) không bị P5 chặn. Remote (P6) ghép vào sau qua cùng
`MemoryClientProtocol` — runtime không sửa một dòng.

---

## 2. P0-recovery — dùng nguyên `BUILD_SPEC.md` STEP 1–5

**Không viết lại.** `BUILD_SPEC.md` STEP 1–5 chính là P0-recovery:

- STEP 1: khôi phục `RuleBasedIntentParser`
- STEP 2: sửa `base.py` self-import + tách `__init__.py`
- STEP 3: khử trùng class `IntentPlanner`
- STEP 4: hợp nhất `SourceType` enum
- STEP 5: import-sanity gate + chạy lại P0 suite

→ Hết STEP 5: `python main.py` chạy, `pytest` xanh. **Đó là cổng vào P1-contract.**

### ⛔ ĐÓNG BĂNG STEP 6–9 của BUILD_SPEC cũ (đã chuyển `ARCHIVE_BUILD_SPEC_OLD.md`)

Mục tiêu đổi từ "hardening Agent" sang "MVP integration", nên các step cũ **không
còn nằm trên đường găng**, và một số **sai hướng**:

| STEP cũ                                     | Quyết định mới                          | Lý do                                                                                                                                                                                                 |
| ------------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6 — persist memory nội bộ (`InMemoryStore`) | **THAY bằng `SPEC_memory_client.md`**   | Không persist `InMemoryStore` như mục tiêu cuối. `InMemoryStore` trở thành **backing store của `LocalMemoryClient`**. Memory truy cập qua `MemoryClientProtocol`, không qua `state.memory` trực tiếp. |
| 7 — structured event log                    | **HOÃN (post-MVP)**                     | Hardening, không phải đường tới MVP.                                                                                                                                                                  |
| 8 — retry/timeout                           | **HOÃN (post-MVP)**                     | `web_search` còn fake → chưa có I/O thật cần retry.                                                                                                                                                   |
| 9 — dọn file rỗng                           | **GỘP vào STEP 5** nếu nhanh, hoặc hoãn | Hygiene, không chặn gì.                                                                                                                                                                               |

**Claude Code KHÔNG được tự làm STEP 6–9 cũ.** Sau P0-recovery, chờ spec P1-contract.

---

## 3. Contract `ContextPack` — NGUỒN SỰ THẬT DUY NHẤT

> ⚠️ **Source of truth cho Memory contract:** `agent_core/memory/contracts.py`, đặc tả
> đầy đủ trong **`SPEC_memory_client.md`** (§2 + §7b). Phần dưới đây chỉ là **tóm tắt
> ngữ cảnh** để đọc master plan standalone — KHÔNG phải định nghĩa chính. Nếu lệch nhau,
> `SPEC_memory_client.md` thắng. Claude Code implement theo `SPEC_memory_client.md`, KHÔNG
> theo tóm tắt này.

### Nguyên tắc thiết kế contract

- **Token-budgeted:** Agent gửi `token_budget`, Memory trả về vừa đủ, kèm token thực dùng. Khác biệt kỹ thuật cốt lõi của TOMTIT — đừng bỏ.
- **Service không đoán intent.** Agent gửi `goal` + `budget`, Memory retrieve + rank + cắt. Không suy luận thêm.
- **Structured, không phải blob text.** `ContextPack` là object có field rõ.
- **Versioned từ ngày đầu.** `schema_version` để đổi contract sau không vỡ câm.

### Hình dạng tóm tắt (chi tiết + field degraded/provenance ở `SPEC_memory_client.md`)

- `POST /retrieve` ← `RetrieveRequest{goal, user_id, session_id, token_budget, max_items}`
- → `ContextPack{items[ContextItem], total_items, tokens_used, token_budget, truncated, degraded, memory_source}`
- `POST /write` ← `WriteRequest{user_id, session_id, task_id, candidates[MemoryCandidate]}` → `WriteResponse{written_ids, skipped}`
- `GET /handshake` → `{health_status, ready, backend_version, schema_version, capabilities, latency_ms}` (chỉ dùng ở P5/P6 remote)

### Ba điểm đã CHỐT (không còn là câu hỏi mở)

1. **`ContextItem.type` = `MemoryType` enum** đã có ở Agent (không string tự do) — hai bên không lệch.
2. **TokenCounter:** dùng `ApproxTokenCounter` chung cho MVP — chốt ở `SPEC_memory_client.md §6`. Không thêm dependency tokenizer.
3. **`MemoryClientProtocol` KHÔNG nhận full `AgentState`.** Nhận explicit params (`goal, user_id, session_id, token_budget, max_items`). Runtime tự rút các field ra. Chốt ở `SPEC_memory_client.md §2`.

---

## 4. Map vào runtime flow mục tiêu của bạn

Flow bạn đã định nghĩa, đánh dấu phần MVP này chạm tới:

```
UserMessage
  → TurnClassifier              [post-MVP, chưa làm]
  → MemoryClient.retrieve_context_pack(goal, *explicit state-derived params*)   ★ P2/P3
  → IntentParser                [P0-recovery — RuleBasedIntentParser]
  → SlotValidator               [đã có]
  → IntentPlanner               [đã có]
  → PlanValidator               [đã có]
  → ToolExecutor                [đã có — single gate]
  → Observation/EventLog        [event log: post-MVP STEP 7]
  → FinalComposer               [đã có]
  → MemoryClient.write_memory_candidates(...)         ★ P2/P3
  → AgentState.complete()       [đã có]
```

★ = phần P2/P3 thêm vào. Mọi thứ giữa parser và composer **đã tồn tại** (sau khi
P0-recovery sửa import). MVP integration thực chất chỉ là **bọc hai đầu memory** quanh
runtime sẵn có — KHÔNG viết lại runtime.

---

## 5. Cảnh báo founder-mindset (đọc một lần)

- **Đừng để MVP phình.** DoD của bạn là _một luồng end-to-end chạy_. Không phải nhiều turn, không phải `TurnClassifier`, không phải event log, không phải retry hoàn chỉnh. Một luồng. Chạy. Demo được. Dừng.
- **Contract trước code.** P1-contract chốt `ContextPack` (Pydantic) trước khi P2-local-client viết client. Đảo thứ tự = viết lại hai lần.
- **Cùng TokenCounter hai bên** hoặc token budget vô nghĩa — đây là nơi tôi thấy bạn dễ mất nhất.
- Sau P4-local-demo chạy được: **dừng build, đi nói chuyện user**. Một luồng chạy thật + demo là đủ để phỏng vấn design partner. Đừng polish lõi trước khi có tín hiệu thị trường.

---

## 6. Next step (một việc)

Cho Claude Code chạy **P0-recovery = `BUILD_SPEC.md` STEP 1**, đúng lệnh khởi động ở
`BUILD_SPEC.md §5`. Song song, bạn review `§3` (draft `ContextPack`) và trả lời 3
ba điểm đã chốt ở `§3`. Khi P0-recovery qua gate STEP 5, architect viết spec P1-contract
→ P2-local-client. Spec P5-remote-memory (HTTP server) đến sau, cần code TOMTIT-Memory để khớp.
