# REPORT_M7B_SPEC_DRAFT_REVIEW_VERIFIED

**Date:** 2026-06-21 UTC
**Repository:** TOMTIT-Agent
**Candidate:** `docs-m7b-restart-recall-spec-draft @ 607d579ae94ef3b21ad91333ec2242a83ebfab3b`
**Base:** `main == origin/main == 3737ca4d58fd516633013efc05d30106f0a1493a`
**Verification policy:** `docs/standards/VERIFICATION_GATE.md`
**Scope:** READ-ONLY independent review of the M7-B spec draft. No edits.

**Hygiene statement:**
- Code changed: NO
- Tests changed: NO
- Spec changed during review: NO
- Preflight report changed during review: NO
- M7-A spec/inventory changed: NO
- Memory Contract wire/fixtures changed: NO
- TOMTIT-Memory changed: NO
- Planner/skills/tools changed: NO
- Architecture/Product/Gate changed: NO
- `.gitignore` changed: NO
- Commit created: NO · Merge: NO · Push: NO
- M7-B implemented: NO · SF2 implemented: NO
- Only review report created: YES

---

## 0. Candidate and baseline custody

`main == origin/main == 3737ca4`; `docs-m7b-restart-recall-spec-draft == 607d579`; `base_ancestor_exit=0`; exactly one commit from base (`607d579 docs(M7-B): draft restart recall spec`); worktree/staged clean. **PASS**.

## 1. Spec and preflight custody

Spec SHA `b7b17a58d9dd5331d2dacb455114535b44a0d3e8a58cc40f8d148bb804607bd9` (384 lines); header `Version 0.1-draft` / `Status DRAFT FOR ARCHITECT REVIEW — IMPLEMENTATION NOT AUTHORIZED` / baseline `3737ca4`. Preflight SHA `d167c0f2e23a047bf3a8182fb713a74054011a9ec0d1671690ab856df65380fe` (194 lines). All match. **PASS**.

## 2. Branch delta and scope audit

`3737ca4..607d579`:
```
A docs/reports/REPORT_M7B_RESTART_RECALL_PREFLIGHT.md
A docs/specs/SPEC_M7B_RESTART_RECALL.md
```
`git diff --check` clean. Forbidden-path audit (agent_core, tests, main.py, deps, .gitignore, ARCHITECTURE, goal_product, standards, M7-A spec, M7-A inventory): **ZERO**. **PASS**.

## 3. Required section structure review

All 21 required sections (0–20) present and in order (`missing=NONE`, `ordered=True`). **PASS**.

## 4. Product claim and non-goals review

| Check | Status | Evidence |
|---|---|---|
| Narrow product claim | PASS | §2: "recall a previously confirmed project decision … fresh Agent session/process … remote context retrieval … provenance preserved" |
| Stronger restart claim marked optional/smoke target | PASS | §2 optional claim tied to §13 restart smoke |
| Project resume excluded | PASS | §3 non-goals + §15 stop #14 + §16 HIGH risk mitigation |
| SF2 excluded | PASS | §3 |
| Contract v2 excluded | PASS | §3, §5(8), §14 AC-14 |
| TOMTIT-Memory code changes excluded | PASS | §3, §5(9), §14 AC-15 |

18 non-goal/exclusion term hits; 4 claim-term hits. **PASS**.

## 5. Architecture fact grounding review

| Fact | Spec states? | Source/preflight evidence? | Status |
|---|---|---|---|
| retrieve_context_pack exists | YES | YES (`memory/client.py`, `remote_client.py`) | PASS |
| /v1/context/retrieve | YES | YES (`remote_client.py`, Memory `main.py`) | PASS |
| context_pack feeds AgentState | YES | YES (`runtime_agent._retrieve_memory`) | PASS |
| answer_from_context consumes context_pack | YES | YES (`builtin_tools`/registry) | PASS |
| project+user scope (not session) | YES | YES (preflight §4/§5) | PASS |
| provenance fields (memory_id/evidence_ref/source_task_id) | YES | YES (`contracts/v1.py`) | PASS |
| durable SQLite restart evidence | YES | YES (preflight §6 F) | PASS |
| no Contract v2 | YES | YES | PASS |
| no Memory code change | YES | YES | PASS |

No unsupported assumption phrased as fact. **PASS**.

## 6. Same-tick FTS nuance review

§9 records the one immediate same-tick 0-result observation and the fresh-client/direct-query success; requires fresh session/process proof; §10 permits only a narrow bounded stabilization (max 5 attempts, 100–250 ms, stop on first hit, fail loudly) and **explicitly states it is not a generic retry controller / circuit-breaker** and must never mask a true no-result/failure. AC-M7B-17 + tests 18–19 enforce. **PASS**.

## 7. Identity/provenance/output contract review

§7 specifies all isolation rules (same project+user → recall; different user → no; different project → no; new session_id must not block; no dependence on `confirmed_save_operation`). §8/§11.2 define output: content + provenance only when present, no fabrication; no-result `No matching project decision found.`; failure `Decision recall failed.`; no raw backend text. **PASS**.

## 8. File manifest and implementation order review

§17 manifest is Agent-side and bounded (session_runtime, cli; runtime_agent/main/client/remote_client only-if-needed; tests) with an explicit forbidden list (confirmation/tools/skills/planning/wire/fixtures/standards/goal_product/ARCHITECTURE/.gitignore/TOMTIT-Memory). §18 order B0–B8 is dependency-safe (verify retrieval → runtime → session → CLI → tests → restart smoke → gates); Memory code change is not permitted without separate approval. **PASS**.

## 9. Acceptance criteria review

20 ACs (AC-M7B-01…20) cover: baseline/M7-A custody; M7-A write unchanged; `/memory recall` exists; uses existing `retrieve_context_pack`; fresh-session recall; project+user boundary; project isolation; user isolation; provenance preserved; safe no-result; safe remote failure; no local fallback; no `confirmed_save_operation` dependency; no Contract v2/wire; no Memory code change; no planner/tool/skill refactor; bounded same-tick stabilization; real restart smoke; full regression; forbidden-path zero. Each maps to a §12 test or structural inspection. **PASS**.

## 10. Test catalogue review

§12 catalogue is continuous **1–24, no duplicates**, covering command parsing, interactive query, positive/no-result/failure recall, identity isolation (project/user), fresh session/process boundary, provenance, no-fallback, no `confirmed_save_operation` dependency, no planner/tool route, bounded stabilization (+ never-false-positive), contract/M7-A fingerprints, real restart smoke, full regression. **PASS**.

## 11. Stop conditions review

§15 lists 14 specific, detectable, actionable stop conditions including: retrieve primitive unavailable; `/v1/context/retrieve` unavailable; requires Contract v2; requires Memory code change; requires local fallback; identity boundary unprovable; provenance unpreservable; same-tick not boundable; requires planner/tool/skill refactor; requires standards/.gitignore change; restart smoke not runnable; would read `confirmed_save_operation`; would expose raw error; scope-creep to project resume. **PASS**.

## 12. Risk register review

§16 classifies all required risks (FTS timing LOW; retrieval relevance MEDIUM; identity scoping LOW; session_id-not-in-scope LOW; provenance/privacy MEDIUM; context truncation MEDIUM; no-result false negative MEDIUM; restart fixture MEDIUM; scope-creep to project resume HIGH) — each with a mitigation; the single HIGH (project-resume creep) mitigated by hard non-goals + stop #14; no CRITICAL. **PASS**.

## 13. Non-authorization review

`Implementation authorization: NOT AUTHORIZED` (header); §0 and §20 state the draft authorizes nothing, GO does not authorize implementation, freeze requires a committed frozen revision + recorded SHA, and implementation requires a separate instruction citing the frozen spec. Cannot be misread as authorization. **PASS**.

## 14. Regression

`import_ok`; **552 passed**; exit 0 (Python 3.11.2, pytest 8.4.2, Darwin 25.5.0). **PASS**.

## 15. Final hygiene

`branch == docs-m7b-restart-recall-spec-draft`; `HEAD == 607d579`; `main == origin/main == 3737ca4`; worktree/staged clean; only untracked reports present (review report added). No edits/commit/merge/push during review. **PASS**.

## 16. M7B-REVIEW-01 through M7B-REVIEW-22

| ID | Criterion | Status |
|---|---|---|
| M7B-REVIEW-01 | candidate branch exact at 607d579 | PASS |
| M7B-REVIEW-02 | base main/origin exact at 3737ca4 | PASS |
| M7B-REVIEW-03 | spec SHA/lines exact | PASS |
| M7B-REVIEW-04 | preflight SHA/lines exact | PASS |
| M7B-REVIEW-05 | branch delta exactly two docs files | PASS |
| M7B-REVIEW-06 | no forbidden path drift | PASS |
| M7B-REVIEW-07 | required sections present and ordered | PASS |
| M7B-REVIEW-08 | product claim narrow and safe | PASS |
| M7B-REVIEW-09 | non-goals strong enough | PASS |
| M7B-REVIEW-10 | architecture facts grounded | PASS |
| M7B-REVIEW-11 | same-tick FTS nuance handled correctly | PASS |
| M7B-REVIEW-12 | identity boundary complete | PASS |
| M7B-REVIEW-13 | provenance/output contract complete | PASS |
| M7B-REVIEW-14 | file manifest bounded | PASS |
| M7B-REVIEW-15 | implementation order safe | PASS |
| M7B-REVIEW-16 | AC list complete and testable | PASS |
| M7B-REVIEW-17 | test catalogue continuous and complete | PASS |
| M7B-REVIEW-18 | stop conditions actionable | PASS |
| M7B-REVIEW-19 | risk register complete with mitigations | PASS |
| M7B-REVIEW-20 | non-authorization explicit | PASS |
| M7B-REVIEW-21 | regression passes (552) | PASS |
| M7B-REVIEW-22 | no edits/commit/merge/push during review | PASS |

22 / 22 PASS. No FAIL/UNVERIFIED/WAIVED.

## 17. Residual risks

1. **Informational** — draft is `0.1-draft`; architect may still request wording changes before freeze.
2. **LOW** — retrieval relevance/query strategy for recall is a spec-level intent; the implementation phase must pick a concrete recall query and assert it returns the saved decision (covered by AC + test catalogue).
3. **External (not this task)** — sibling TOMTIT-Memory has an unrelated uncommitted `docs/STATUS.md` edit (Memory HEAD unchanged `d4d879d`); untouched.

No blocker.

## 18. Final verdict

```
M7-B SPEC DRAFT REVIEW: GO
READY FOR M7-B SPEC FREEZE REVIEW
```

M7-B spec draft `607d579` is suitable to proceed to a freeze review: custody exact; docs-only scope with zero forbidden-path drift; all 21 sections present and ordered; narrow recall claim with strong non-goals; architecture facts grounded in source/preflight; same-tick FTS nuance correctly bounded (not a generic retry feature); complete identity/provenance/output contracts; bounded Agent-only manifest and dependency-safe order; 20 testable ACs; continuous 1–24 test catalogue; 14 actionable stop conditions; risk register with mitigations; explicit non-authorization; 552 tests pass. No patch required.

`GO` does not authorize freeze, merge, push, or implementation. Next step: architect freeze review (a separate instruction) → frozen spec at a committed revision with recorded SHA → separate M7-B implementation instruction.

Code changed: NO · Tests changed: NO · Spec changed: NO · Preflight changed: NO · M7-A spec/inventory changed: NO · Memory Contract/wire/fixtures changed: NO · TOMTIT-Memory changed: NO · planner/skills/tools changed: NO · Architecture/Product/Gate changed: NO · `.gitignore` changed: NO · Commit/Merge/Push: NO · M7-B implemented: NO · SF2: NO · Only review report created: YES.
