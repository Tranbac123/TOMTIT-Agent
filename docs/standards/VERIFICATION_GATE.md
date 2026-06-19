# Chuẩn Verification Gate cho AI Agent

**Tên file:** `VERIFICATION_GATE.md`  
**Phiên bản:** `1.0.0`  
**Trạng thái:** `PROPOSED FOR ADOPTION`  
**Áp dụng cho:** AI coding agent, implementation agent, verifier/reviewer, CI verification job, TOMTIT-Agent, TOMTIT-Memory và các repository liên quan.

---

## 1. Mục đích

Tài liệu này định nghĩa verification gate bắt buộc trước khi một thay đổi, milestone hoặc phase được đề nghị phê duyệt.

Hai trạng thái sau phải được tách biệt:

```text
IMPLEMENTED
= code/config đã được thay đổi

VERIFIED
= candidate revision đã được đối chiếu với acceptance criteria
  bằng bằng chứng có thể tái lập
```

Không được coi một phase là hoàn thành chỉ vì code đã viết xong, một nhóm test đã xanh hoặc Agent nói rằng thay đổi “có vẻ đúng”.

---

## 2. Ngôn ngữ quy phạm

Các từ khóa sau có ý nghĩa bắt buộc:

- **MUST / MUST NOT:** bắt buộc hoặc tuyệt đối không được làm.
- **SHOULD / SHOULD NOT:** nên tuân thủ; chỉ được bỏ qua khi có waiver do con người phê duyệt.
- **MAY:** tùy chọn.

---

## 3. Nguyên tắc cốt lõi

1. Mỗi phase phải bắt đầu từ một baseline revision đã được chấp nhận.
2. Acceptance criteria phải được định nghĩa trước implementation và map sang bằng chứng cụ thể.
3. Verification là một hoạt động riêng biệt và read-only.
4. Candidate revision, spec, criteria, fixtures, dependencies và verification policy phải được freeze trong lúc verify.
5. Report chỉ là chỉ mục trỏ tới bằng chứng, không thay thế bằng chứng.
6. Full test suite xanh không chứng minh criterion chưa được test.
7. Thay đổi ngoài scope làm gate dừng ngay.
8. Criterion chưa được xác minh luôn chặn phase transition.
9. `GO` chỉ có nghĩa là “đủ điều kiện đề nghị human/architect phê duyệt”.
10. AI Agent không được tự động mở phase tiếp theo sau khi báo `GO`.

---

## 4. Vai trò

### 4.1 Implementer

Implementer được thay đổi code, test, fixture, docs và config trong phạm vi đã được cho phép.

Implementer không được tự coi implementation report của mình là phê duyệt cuối cùng.

### 4.2 Verifier

Verifier kiểm tra candidate revision đã freeze và chạy verification plan.

Verifier phải read-only đối với:

- production source;
- tests;
- canonical fixtures;
- accepted specs;
- dependency manifests và lockfiles;
- schema và migrations;
- Git history và worktree.

Verifier chỉ được ghi log/evidence vào:

- thư mục artifact nằm ngoài source tree; hoặc
- thư mục artifact riêng đã được ignore và phê duyệt.

### 4.3 Approver

Approver là con người hoặc architect được ủy quyền rõ ràng.

Chỉ approver được:

- phê duyệt waiver;
- chấp nhận candidate revision;
- mở phase tiếp theo;
- cho phép thay đổi contract hoặc architecture.

AI Agent không được tự tạo hoặc tự phê duyệt waiver.

---

## 5. Immutable identifiers bắt buộc

Mỗi verification report phải ghi:

```text
repository
branch
baseline_commit_sha
candidate_commit_sha
accepted_spec_version_or_hash
acceptance_criteria_version_or_hash
verification_policy_version
fixture_version_or_hash
schema_or_migration_version, nếu có
dependency_lockfile_hash, nếu có
```

Định nghĩa:

- **Baseline commit:** revision đã được chấp nhận trước implementation hiện tại.
- **Candidate commit:** revision đã freeze và đang được đề nghị phê duyệt.
- **Delta:** `baseline_commit..candidate_commit`.

Bất kỳ thay đổi nào đối với candidate code, spec, acceptance criteria, fixtures, dependency manifest/lockfile, schema, migration hoặc verification policy đều làm verification hiện tại mất hiệu lực.

Khi đó phải tạo candidate revision mới và chạy lại gate từ đầu.

---

## 6. Pre-implementation gate

Trước khi sửa code, implementer phải xác định:

### 6.1 Current step

- tên phase/task;
- mục tiêu;
- phạm vi được phép;
- phạm vi bị cấm;
- baseline commit SHA.

### 6.2 Acceptance criteria

Mỗi criterion phải kiểm chứng được khách quan.

Mỗi criterion phải được map sang ít nhất một verification method trước khi implementation bắt đầu.

Ví dụ:

| Acceptance criterion | Bằng chứng bắt buộc |
|---|---|
| Remote outage không làm crash ordinary task | Integration test terminate remote process |
| Remote mode không fallback local memory | Registry inspection + fail-on-access local store |
| Dữ liệu tồn tại sau restart | Cross-process E2E với cùng durable DB |
| Contract error phải fail loud | Invalid-schema response test |
| Side effect phải qua approval | Negative-path test chứng minh tool function không được gọi |

Nếu không thể xác định bằng chứng đáng tin cậy, criterion chưa sẵn sàng để implementation.

### 6.3 Scope manifest

Phase quan trọng nên có scope manifest kiểm tra được bằng máy.

Ví dụ:

```yaml
allowed_paths:
  - agent_core/memory/**
  - tests/memory/**

forbidden_paths:
  - agent_core/policy/**
  - migrations/**

allowed_change_types:
  - add
  - modify

forbidden_change_types:
  - delete
  - rename
```

Scope manifest phải được review trước implementation.

---

## 7. Candidate freeze

Trước verification:

1. Implementation phải được commit.
2. Candidate commit SHA phải được ghi lại.
3. Worktree phải sạch, trừ khi task là recovery/audit dirty worktree.
4. Spec và acceptance criteria phải được freeze.
5. Verification plan phải được freeze.
6. Verifier phải so candidate với accepted baseline.

Bằng chứng Git tối thiểu:

```bash
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git diff --check
git diff --stat <baseline>..<candidate>
git diff --name-status <baseline>..<candidate>
git diff <baseline>..<candidate>
```

Candidate có staged, unstaged hoặc untracked change không được giải thích rõ là `NO-GO`.

---

## 8. Read-only verification policy

Verification pass là read-only.

Trong verification, verifier không được:

- sửa source;
- sửa test;
- sửa fixture;
- sửa spec;
- sửa dependency manifest hoặc lockfile;
- chạy formatter/auto-fix có ghi file;
- generate migration;
- commit, amend, merge, rebase, stash, checkout, reset, clean hoặc push;
- cài dependency không được khai báo;
- thay đổi acceptance criteria;
- làm yếu behavior đang cần chứng minh.

Nếu phát hiện cần sửa:

```text
verification result = NO-GO
→ quay lại implementation
→ tạo candidate revision mới
→ chạy verification lại từ đầu
```

Verifier không được vừa sửa candidate vừa tiếp tục cùng một verification cycle.

---

## 9. Anti-test-gaming rules

Implementer và verifier không được:

- xóa test đang fail để đạt pass;
- làm yếu assertion;
- tăng tolerance không có requirement;
- thêm `skip`, `xfail` hoặc suppression tương đương khi chưa có waiver;
- catch exception quá rộng chỉ để ngăn test fail;
- sửa canonical fixture cho khớp implementation;
- mock bỏ chính boundary/behavior đang cần chứng minh;
- thay cross-process requirement bằng in-process unit test;
- chỉ chạy subset thuận lợi rồi bỏ regression/full suite bắt buộc;
- dùng test không có assertion có ý nghĩa làm bằng chứng;
- generate expected output từ candidate rồi dùng chính output đó để xác nhận candidate.

Nếu legacy test mâu thuẫn accepted contract mới, phải báo contract conflict. Không được âm thầm sửa test trong verification.

---

## 10. Integrity của bằng chứng

Report là chỉ mục trỏ tới evidence, không phải evidence.

Với mỗi command, phải ghi:

```text
exact command
working directory
start timestamp
end timestamp
exit code
stdout/stderr artifact path
artifact SHA-256
environment fingerprint
```

Mẫu machine-readable:

```json
{
  "command": "python -m pytest -q",
  "cwd": "/workspace/tomtit-agent",
  "started_at": "2026-06-18T08:00:00Z",
  "finished_at": "2026-06-18T08:00:09Z",
  "exit_code": 0,
  "summary": "298 passed in 8.41s",
  "log_path": "/tmp/verification/full-pytest.log",
  "log_sha256": "<sha256>",
  "environment_id": "<environment-fingerprint>"
}
```

Evidence artifact không được chứa:

- secret hoặc credential;
- private memory content;
- raw production data;
- unrestricted personal information.

Nếu hệ thống không thể lưu artifact/log có hash, report phải ghi rõ evidence integrity yếu hơn và đánh dấu risk tương ứng.

---

## 11. Fresh environment và reproducibility

Các gate liên quan architecture, persistence, safety, contract hoặc production phải chạy trong fresh environment.

Report phải ghi:

- OS hoặc container image;
- runtime version;
- package-manager version;
- dependency versions;
- database version;
- tokenizer/model/runtime version khi liên quan;
- exact install command;
- exact test command;
- random seed khi liên quan;
- locale/timezone khi behavior phụ thuộc chúng.

Dependency phải được cài từ accepted manifest và lockfile, hoặc từ quy trình setup có thể tái lập đã được tài liệu hóa.

Verifier nên kiểm tra dependency leakage từ:

- global packages;
- editable sibling repositories;
- undeclared environment variables;
- cached/generated files;
- implicit `PYTHONPATH`;
- local services không được khai báo bởi test harness.

Fresh-environment gate không chạy được thì trạng thái là `UNVERIFIED`, không phải `PASS`.

---

## 12. Các lớp verification bắt buộc

Verifier phải chạy mọi check phù hợp với phase.

### 12.1 Repository và scope

- branch/revision;
- worktree state;
- staged/unstaged/untracked files;
- baseline-to-candidate diff;
- allowlist/denylist scope;
- deletions/renames;
- `git diff --check`.

### 12.2 Direct acceptance tests

- test map trực tiếp tới acceptance criteria;
- negative-path tests;
- failure-path tests;
- boundary tests;
- security/safety tests khi liên quan.

### 12.3 Regression

- subsystem suite liên quan;
- full repository suite khi khả thi;
- test bảo vệ các invariant đã được accepted.

### 12.4 Static/build checks

Khi phù hợp:

- import check;
- lint;
- formatting check không ghi file;
- type-check;
- build/package check;
- schema validation;
- migration dry run;
- fixture parity;
- API/OpenAPI validation.

### 12.5 End-to-end

Bắt buộc khi criterion liên quan:

- process restart;
- persistence;
- external HTTP contract;
- network failure;
- cross-repository integration;
- real tool execution;
- deployment/startup behavior.

Mocked unit test không được thay black-box E2E bắt buộc.

---

## 13. Repeatability và flaky-test policy

Test liên quan subprocess, networking, concurrency, SQLite locking, async, timing, restart hoặc E2E phải chứng minh repeatability.

Mặc định:

```bash
for i in 1 2 3; do
  <targeted verification command> || exit 1
done
```

Kết quả yêu cầu: `3/3 pass`.

Harness nên dùng polling có deadline hữu hạn, không dùng sleep dài để che race.

Flaky pass không được coi là pass.

Intermittent failure phải được xử lý hoặc có waiver do con người phê duyệt.

---

## 14. Warning policy

Mọi warning phải được ghi và phân loại.

| Severity | Ý nghĩa | Gate action |
|---|---|---|
| `BLOCKER` | Correctness, data loss, resource leak, security, schema hoặc contract risk | `NO-GO` |
| `HIGH` | Product hoặc architecture risk đáng kể | Phải sửa hoặc có waiver |
| `MEDIUM` | Không chặn nhưng cần xử lý | Phải có owner và target phase |
| `LOW` | Cleanup nhỏ hoặc deprecation đã biết | Phải có backlog |
| `EXTERNAL` | Đã chứng minh thuộc tool/environment bên ngoài | Ghi evidence và owner |

Unclosed socket, file handle, DB connection, orphan process, security warning và schema warning không được bỏ qua khi chưa có bằng chứng.

---

## 15. Trạng thái của từng criterion

Mỗi acceptance criterion nhận đúng một trạng thái:

| Status | Định nghĩa |
|---|---|
| `PASS` | Có đủ bằng chứng tái lập chứng minh criterion |
| `FAIL` | Bằng chứng cho thấy criterion không đạt |
| `UNVERIFIED` | Chưa hoặc không thể kiểm tra |
| `WAIVED` | Ngoại lệ được human approver chấp nhận |

Quy tắc:

- `UNVERIFIED` luôn dẫn tới `NO-GO`.
- `FAIL` luôn dẫn tới `NO-GO`.
- `WAIVED` cần waiver record bất biến.
- AI Agent không được tự tạo hoặc tự duyệt waiver.

Waiver record phải có:

```text
criterion_id
approver
reason
risk
scope
expiration_or_review_date
tracking_issue
```

---

## 16. Out-of-scope change policy

Nếu phát hiện thay đổi ngoài scope, verifier phải:

1. Dừng verification.
2. Capture repository metadata và diff hiện tại làm evidence.
3. Đánh dấu `NO-GO`.
4. Chỉ rõ file và change type ngoài scope.
5. Chờ architect instruction.

Verifier không được:

- sửa;
- stash;
- reset;
- commit;
- revert;
- clean;
- move;
- delete;
- “backup rồi tiếp tục”.

Mọi thao tác preservation/recovery phải là task riêng được authorize rõ ràng.

---

## 17. Architecture và contract regression gate

Verification phải kiểm tra candidate không phá accepted contract hoặc boundary.

Các invariant tích lũy của TOMTIT:

```text
AgentState
= source of truth cho một task/run

SessionState
= source of truth cho continuity/history của một session

TOMTIT-Memory
= source of truth cho durable semantic memory qua nhiều session

MemoryClientProtocol
= Agent-side durable-memory integration boundary

ToolExecutor + PolicyEngine + ApprovalGate
= side-effect safety boundary
```

Khi liên quan, verifier phải kiểm tra:

- không có direct durable-persistence path bypass `MemoryClientProtocol`;
- local và remote durable memory không active cùng lúc;
- HTTP/transport details không leak vào runtime state;
- memory vẫn là untrusted evidence, không phải privileged instruction;
- `SessionState` không trở thành semantic-memory store;
- tool không bypass policy, approval hoặc executor;
- phase hiện tại không triển khai scope của phase sau;
- frozen wire contract, fixture, enum, route, schema và semantics không bị đổi khi chưa được phê duyệt.

Test suite xanh không được dùng để bỏ qua architecture violation.

---

## 18. Verification depth theo mức rủi ro

### Level 1 — Local change

Ví dụ: comment, pure helper biệt lập, docs rủi ro thấp.

Tối thiểu:

- diff/scope check;
- targeted validation/test;
- import/build check liên quan.

### Level 2 — Subsystem change

Ví dụ: planner, tool registry, memory client, service layer.

Tối thiểu:

- targeted acceptance tests;
- subsystem regression suite;
- full suite khi khả thi;
- architecture-boundary inspection;
- fresh-environment khi dependency thay đổi.

### Level 3 — Critical change

Ví dụ: contract, schema, persistence, concurrency, policy/safety, cross-repo integration, deployment.

Tối thiểu:

- independent verifier khi khả thi;
- committed candidate đã freeze;
- fresh environment;
- black-box E2E;
- negative-path verification;
- repeatability run;
- full regression suites;
- evidence artifacts có hash;
- explicit human approval.

---

## 19. Independent verification

Với Level 3, verifier nên khác implementer.

Workflow ưu tiên:

```text
Implementer agent
→ committed candidate revision
→ independent verifier agent hoặc CI job
→ human/architect approval
```

Verifier nên dùng clean checkout và nên inspect candidate trước khi đọc kết luận chủ quan của implementer.

Nếu không có independent verification, report phải ghi limitation và residual risk.

---

## 20. GO / NO-GO decision

### 20.1 Điều kiện đề nghị GO

Verifier chỉ được đề nghị `GO` khi:

- mọi criterion là `PASS` hoặc có `WAIVED` hợp lệ;
- không có `FAIL` hoặc `UNVERIFIED`;
- repository scope sạch;
- không có architecture/contract blocker;
- targeted tests bắt buộc pass;
- regression/full suites bắt buộc pass;
- fresh-environment gate bắt buộc pass;
- E2E và repeatability gate bắt buộc pass;
- evidence integrity đạt yêu cầu;
- không còn blocking warning.

### 20.2 NO-GO

Nếu thiếu hoặc fail bất kỳ điều kiện bắt buộc nào, kết quả là `NO-GO`.

Report phải liệt kê exact actions cần hoàn tất trước verification attempt mới.

### 20.3 Human authorization

`GO` chỉ có nghĩa:

```text
Candidate revision đủ điều kiện để human/architect xem xét phê duyệt.
```

Không có nghĩa:

```text
AI Agent được phép tự động bắt đầu phase tiếp theo.
```

Agent phải dừng sau report và chờ authorization rõ ràng.

---

## 21. Mẫu verification report bắt buộc

```markdown
## Current step

- Phase/task:
- Objective:
- Baseline commit:
- Candidate commit:
- Spec/criteria/policy versions:

## Acceptance criteria

| ID | Criterion | Required evidence |
|---|---|---|
| AC-01 | ... | ... |

## Changes inspected

- Branch:
- Files created:
- Files modified:
- Files deleted:
- Staged state:
- Unstaged state:
- Untracked state:
- Baseline-to-candidate diff:
- Out-of-scope changes:

## Verification commands and results

### Command V-01

- Command:
- Working directory:
- Start/end time:
- Exit code:
- Tests collected:
- Passed:
- Failed:
- Skipped:
- Warnings:
- Log artifact:
- Log SHA-256:
- Environment fingerprint:

## Criteria-by-criteria evidence

| Criterion | Evidence | Status |
|---|---|---|
| AC-01 | V-01, test path, assertion | PASS / FAIL / UNVERIFIED / WAIVED |

## Unverified assumptions

- ...

## Regressions and architecture risks

- Contract compatibility:
- State boundaries:
- Safety/policy boundaries:
- Existing behavior regression:
- Scope leakage:
- Dependency/schema risks:

## Warning classification

| Warning | Severity | Evidence | Owner | Required action |
|---|---|---|---|---|

## GO / NO-GO decision

`GO` hoặc `NO-GO`

Reason:

## Required actions before next step

1. ...
```

---

## 22. Minimum command checklist

Điều chỉnh command theo repository, nhưng không bỏ check phù hợp.

### Repository

```bash
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git diff --check
git diff --stat <baseline>..<candidate>
git diff --name-status <baseline>..<candidate>
```

### Tests

```bash
<targeted acceptance tests>
<subsystem regression tests>
<full test suite>
<warning audit>
```

### Static/build

```bash
<import check>
<lint check>
<type check>
<build/package check>
<schema/fixture/API validation>
```

### Repeatability

```bash
for i in 1 2 3; do
  <critical targeted test command> || exit 1
done
```

### Final hygiene

```bash
git status --short --untracked-files=all
git diff --check
```

---

## 23. Enforcement recommendations

Tài liệu này là process standard, chưa phải enforcement mechanism hoàn chỉnh.

Repository quan trọng nên enforce thêm bằng:

- `AGENTS.md`, `CLAUDE.md` hoặc instruction tương đương;
- CI required checks;
- protected branches;
- required code review;
- immutable build artifacts;
- dependency lockfiles;
- read-only verifier credentials;
- restricted agent capabilities;
- machine-readable phase/scope manifests.

Capability policy khuyến nghị cho verifier:

```text
source_write = false
test_write = false
fixture_write = false
git_mutation = false
dependency_mutation = false
artifact_write = true
command_execution = true
```

Soft prompt rule nên được hỗ trợ bởi runtime hoặc CI enforcement đối với production-critical gate.

---

## 24. Quy tắc áp dụng

Mọi prompt implementation trong tương lai nên tham chiếu file này thay vì lặp lại một phiên bản rút gọn dễ bị drift.

Clause khuyến nghị:

```text
Trước khi đề nghị phê duyệt hoặc chuyển phase, hãy thực hiện verification
được định nghĩa trong VERIFICATION_GATE.md trên candidate revision đã freeze.
Dừng sau report. Không bắt đầu phase tiếp theo nếu chưa có explicit human
hoặc architect authorization.
```

Project-specific rule có thể nghiêm ngặt hơn nhưng không được làm yếu chuẩn này.
