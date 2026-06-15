# VALIDATION_PLAN.md

> Kế hoạch kiểm chứng với người dùng thật sau P4.
> Mục tiêu: xác định pain thật trước khi quyết định P5/P6 hay đổi hướng.
> Không phải spec kỹ thuật. Không tạo feature mới trước khi có kết quả validation.

---

## Artifact demo (đã sẵn)

```bash
python3.11 main.py
```

Chạy 4 scenarios. Scenario đáng chú ý nhất cho validation:

| Scenario | Điểm chứng minh |
|----------|----------------|
| 2 — Calculate | Agent KHÔNG disclosure dù store có memory → không nhiễu |
| 3 — Compound | Agent disclosure đúng khi task thực sự ghi memory |
| 4 — Project context | Agent nhớ quyết định kỹ thuật, trả lời đúng từ ContextPack |

Scenario 4 là DoD của P4: seed 1 DECISION item ("MVP dùng FTS5") → query → agent trả đúng.

---

## Script demo 3–5 phút

```
[00:00] python3.11 main.py — chạy cả 4 scenarios
[00:30] Chỉ Scenario 2: "Kết quả: 60.0" — không có disclosure.
        "Agent biết store có data nhưng không nhiễu khi task không liên quan."
[01:30] Chỉ Scenario 3: có disclosure "memory rút gọn" vì task ghi memory.
        "Khi task thực sự dùng memory, agent thông báo."
[02:30] Chỉ Scenario 4: Context consumed: True / "FTS5" in answer / disclosure.
        "Agent nhớ quyết định kỹ thuật đã seed — trả lời từ context, không hallucinate."
[03:30] Hỏi: "Trong workflow hàng ngày, bao giờ bạn cần agent nhớ điều gì từ session trước?"
```

---

## Câu hỏi phỏng vấn

### Phần 1 — Pain mapping

1. Bạn dùng AI assistant (Cursor, Claude Code, Copilot, …) cho task nào thường xuyên nhất?
2. Khi mở session mới, bạn mất gì? (context, quyết định cũ, preference cá nhân, thông tin repo, …)
3. Bạn xử lý điều đó thế nào hiện tại? (copy-paste, system prompt cố định, file README, …)
4. Cách đó mất bao lâu? Bao nhiêu lần/tuần?
5. Mức độ nghiêm trọng: 1 = bất tiện nhỏ / 5 = block công việc thực sự

### Phần 2 — Memory type probing

6. Thứ bạn muốn agent nhớ là loại gì?
   - Quyết định kỹ thuật ("chúng tôi dùng Postgres, không dùng MySQL")
   - Preference cá nhân ("không thêm comment obvious", "dùng snake_case")
   - Fact về repo ("project này dùng pnpm, không phải npm")
   - Lịch sử task ("tuần trước tôi đã sửa bug X theo cách Y")
7. Cần nhớ bao lâu? Trong session / qua nhiều session / vĩnh viễn?
8. Chỉ bạn xem hay cả team cần thấy?

### Phần 3 — Willingness

9.  Nếu agent tự nhớ và recall đúng 80% thời gian, bạn có dùng không?
10. Điều gì khiến bạn KHÔNG dùng? (privacy, accuracy thấp, latency, không kiểm soát được, …)
11. Bạn sẵn sàng trả thêm bao nhiêu ($/tháng) cho tính năng này?

---

## Mẫu ghi lại (1 người = 1 row)

| Field | Ghi chú |
|-------|---------|
| Pain hiện tại | (quote nguyên văn nếu được) |
| Workaround | (họ đang làm gì) |
| Tần suất | daily / weekly / per-project / one-off |
| Severity | 1–5 |
| Memory type cần | decision / fact / preference / history / none |
| Same-session recall? | yes / no |
| Cross-session recall? | yes / no |
| Team memory? | yes / no |
| Willing to try | yes / maybe / no (reason) |
| Willing to pay | $0 / $1–5 / $5–10 / >$10/mo |

---

## Tiêu chí quyết định sau validation

| Kết quả | Quyết định |
|---------|-----------|
| >50% cần cross-session recall, severity ≥ 3, willing to pay | → P5/P6 (remote memory) |
| >50% chỉ cần same-session, severity ≥ 3 | → Two-run demo (seed run 1, recall run 2) — không cần P5 |
| Pain chủ yếu không phải memory (UX, latency, accuracy) | → Đổi wedge — không build memory |
| <30% có pain rõ ràng | → Phỏng vấn thêm hoặc đổi ICP |

---

## ICP mục tiêu

Cursor users / Claude Code users viết code hàng ngày, làm việc trên project kéo dài >1 tuần,
có trải nghiệm bị mất context giữa sessions.

---

## Trạng thái

P4 CLOSED. Feature development DỪNG. Validation chưa bắt đầu.
Không build feature mới trước khi có kết quả từ ít nhất 5 cuộc phỏng vấn.
