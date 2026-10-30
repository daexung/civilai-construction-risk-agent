# Calculation coverage review - 2026-10-18

Master plan: `docs/plans/CALCULATION-AUTOMATION-MASTER-PLAN.md`.

## Denominators and official contents reconciliation

- The pinned 2026 PDF contents pages 3 through 51 contain **222 parent sections** and **1,095 third-level sections** across the five divisions. A third-level section is the official section denominator; it is not automatically a calculation-work-item denominator because the contents also include policies, lookups, and other non-calculation sections.
- Current draft inventory: **1,058 work-entry proxies**. **1,044** match a third-level contents identity exactly; **51** third-level contents identities have no exact draft row; **14** draft rows have no exact third-level contents identity. The 14 include resource-code-like IDs and section identity mismatches. Neither unmatched group is silently excluded or declared a calculation omission.
- Parsed chunk identities: **1,120** unique `(division, section_no)` pairs; **1,086** match a contents third-level identity. There are **65** parsed identities without an exact draft row and **3** draft rows without an exact parsed identity. The parser misses **9** third-level contents identities and emits **34** identities that do not exact-match a third-level contents entry; some may be parent sections or continuation artifacts. **15** parsed identities have a null/empty division, and **204** section numbers recur across divisions. Parent/continuation links and extraction errors remain unresolved.
- Calculation-work denominator: **unresolved**. The JSON now contains every parsed-only candidate, draft-only candidate, parent section, and third-level contents row with pages and match flags. Each third-level row remains `not_yet_assessed` for calculation-work classification until its source page and parent/continuation scope are reviewed.
- Table-note/reference-rule denominator: **not enumerated**. Parser has 2,304 table chunks (335 contain the remarks-cell marker). Table cells mix rows and notes and are not fully mapped to executable rules. No rule-level completion percentage is reported.

## Current status

- Draft report: 1058 entries; 957 marked `ok`; format issues in 1, citation issues in 100, chunk mismatches in 41; categories overlap. Open questions: 1304.
- Historical legacy index was 382 basic pass, 339 failure, and 337 unassessed. Current integrated replay is 475 basic pass, 249 failures (186 calculator/rule-gate, 52 format/citation preflight, 11 source preflight), 332 skipped for unsupported calculator family, and 2 misfiled exclusions. These statuses are mutually exclusive over 1,058 proxies; 661 unique records reached a calculator. A basic pass is not all-condition verification.
- Draft calc types: `{"per_unit": 492, "not_calculable": 277, "lookup_only": 59, "adjusted_daily_crew": 226, "rate": 4}`.
- Full-rule calculation verification across the inventory: **0**. The machine work queue now records source-rule, executor, calculation, generation, consultation, aggregate, and Excel status separately for all 1,058 draft proxies. Narrow manually authored formwork replay is separate.
- Real automatic-generation verified: **0**. The model-call budget is exhausted; no new call was made.
- Approved JSON module files: 2. Approved isolated-Python registry entries: 0. Presence is not full-section verification.

## Evidence categories

| Area | Verified | Not established |
|---|---|---|
| Source and parse | 982-page map, 4,813 full chunks, section identities counted | Complete source fidelity and extraction of every note/reference |
| Execution spec | 1,058 draft entries, 1,844 table objects, 1,033 explicit rule-like objects | Completeness against official work catalog |
| Runtime expression | Legacy index shows basic pass/fail records | Every condition per item; common capability mapping |
| Actual calculation | Manual formwork candidate: authoring 4/4 prior, corrected regression 9/9 | Independent generation; all-section accuracy |
| Automatic generation | Offline semantic and isolated-Python mock paths prove preflight/contract, execution-feedback, bounded-repair, separate final evaluation, and candidate quarantine across formwork plus two other calculator types | Real-model candidate success; per-section semantic quality; all-section generation |
| Consultation / aggregate / Excel | Original branch single-item checks passed; current-main PR #46 focused two-item dialogue, edit isolation, restore, aggregate, and ordered XLSX regression passed in integration worktree | All-inventory product integration, every calculator through product path, production deployment, and real model generation |
| Registration/deployment | Two JSON module files; Python registry empty | Full provenance migration approval and deployment validation |

## Common defects

### C1 - Source/parse evidence fidelity: table-note cells and referenced clauses lack a normalized complete rule inventory and stable locator mapping across all sections.

Evidence: Draft report has citation issues and chunk mismatches; only one section policy anchor has been checked end-to-end against a labeled table note.

Affected inventory: Parsed table chunks and source rules derived from table notes/referenced text; per-item map remains unbuilt.

Completion: Every calculation-related source note/reference has a stable locator and explicit rule mapping or a reasoned exclusion.

### C2 - Legacy execution index is partial and uses a denominator different from the current draft inventory.

Evidence: Execution index has pass/fail records for fewer than the 1,058 draft work entries; stored summary total differs from the record counts.

Affected inventory: All draft work entries.

Completion: Versioned execution index records exact IDs, denominator and execution semantics.

### C3 - Common calculator expression/type coverage is incomplete or not mapped to all draft calc types.

Evidence: Failures include base-unit parsing and row/column resolution, plus unresolved/blocked/rejected classes; generated interpreter is daily-output focused.

The 339 stored basic failures are now grouped provisionally by recorded reason string in the JSON, with affected work-item and execution-record IDs. This is triage evidence, not confirmed root-cause diagnosis; each cluster must be reproduced before changing shared code.

| Recorded-reason group | Failure records | Work items |
|---|---:|---:|
| Unit parsing | 173 | 173 |
| Table row/column resolution | 73 | 73 |
| Format/citation record | 53 | 53 |
| Applicability/policy block | 17 | 17 |
| Spec data shape/numeric parsing | 14 | 14 |
| Source table alignment | 3 | 3 |
| Calculator input rejection | 2 | 2 |
| Unclassified | 4 | 4 |

These categories are mutually exclusive for the recorded 339 rows; they are string-based triage classes, not validated causal diagnoses.

Affected inventory: Existing failed execution records and entries absent from index; exact capability mapping pending.

Completion: Reproduce and group failures by shared unit/expression/table-resolution feature and list affected work IDs.

### C4 - Fixture/provenance integrity requires encoding-safe versioning and explicit condition values.

Evidence: Index-based complexity fixture contradicted its expected value; v2 correction had encoding corruption; v3 is valid.

Affected inventory: Nine formwork regression cases and future authoring fixtures.

Completion: Saved bytes parse correctly, hashes are recorded, condition matches source column and test roles remain separated.

### C5 - Real-model generation remains unproven; cross-calculator path mechanics have narrow offline evidence.

Evidence: Nine authorized Gemini requests yielded no valid real candidate; historical saved-response replay differs in schema/source hashes. Two source-backed non-formwork calculation types now passed mock author -> contract -> isolated execution -> bounded repair -> separate final evaluation, but mock responses are not model evidence.

Affected inventory: All draft work entries; real generation success rate is not measurable.

Completion: A fresh-authorized real run creates a candidate, isolated authoring and source-based final sets pass without repair leakage, then consultation/aggregate/Excel integration completes.

### C6 - Parsed section identity does not preserve parent/division metadata consistently.

Evidence: Official contents reconciliation found 1,095 third-level sections and 222 parent sections. Draft exact matches are 1,044; 51 official third-level identities have no exact draft; 14 draft identities have no exact third-level contents match. Parsed data has 1,120 identities, 15 with null/empty division, 204 section numbers reused across divisions, 9 official third-level sections missing from parsed identities, and 34 parsed identities outside the official third-level set.

Affected inventory: All official contents, parse, and draft identities until calculation sections, parent/continuation pages, policies, lookups, and resource IDs are classified.

Completion: Review every unmatched row against page ranges and parent/continuation context, classify calculation work separately from other official sections, link parse chunks and drafts, and establish the calculation-work and rule denominators.

### C7 - Multi-item estimate: implementation exists in current main; integrated regression passed, inventory-wide coverage remains open

The earlier C7 statement was branch-scoped evidence mistakenly generalized to the project. Original branch `codex/single-trade-conditions` at 4b93836 did not contain PR #46. Fetched `origin/main` 168d80a includes PR #46 commit `a0fb3f2`, which implements unified single/multi-item dialogue, item-scoped state, aggregate pricing, and multi-line export.

In the separate integration workspace, `evals/check_unified_estimate_chat.py` passed 12 printed checks against the integrated code: two work items, scope/session restore, aggregate pricing, cross-item reference rejection, editing one item while preserving its sibling, repricing, and XLSX rows. Retrieval is mocked; the production dialogue/session/aggregate/XLSX code is used.

Actual status: **implemented in main and focused regression verified in the integration worktree**. **Integration is not yet committed or production deployed**. The test does not verify every calculator/trade, all item conditions, all cost rules, or model generation. These remain tracked under C1-C6 and per-work-item states. No second multi-item implementation is needed.

Completion for this correction: preserve PR #46 while integrating calculation changes, run its focused regression on the integrated code, and retain project-wide per-item verification gaps separately.

## Per-work detail

The JSON companion contains the complete contents inventory, all 1,058 draft work-entry proxies, 65 parsed-only candidates, 3 draft-only candidates, and explicit workflow states for rule mapping, executor reuse, calculation, automatic generation, consultation, aggregation, and Excel. It reports 382 legacy basic pass observations, 339 failures, 337 unassessed, 0 complete-condition validations, and 0 real automatic generations. It does not claim a calculation-work denominator or rule-level completion.

The ToC and work-queue inventory is reproducible with:

```powershell
.\.venv\Scripts\python.exe evals\reconcile_calculation_inventory.py
```

Focused product checks run for this update:

```powershell
$env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe evals\test_luna_candidate_chat_integration.py
$env:PYTHONPATH='.'; $env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe evals\test_single_trade_conditions.py
```

Both passed (2/2 and 11/11). The integration candidate was exposed and loaded through a test-only registry patch; this is a single-item local test, not real generation, multi-item support, or operating registration.

## 2026-10-18 branch and integration scope correction

The original `codex/single-trade-conditions` worktree at 4b93836 was missing PR #46; this was not evidence that the project lacked multi-item support. Current fetched main is 168d80a426d5a348f666a9d2f03153b818e0fec7 and contains a0fb3f2. Focused integrated regression passed; calculation-coverage counts remain unchanged because one product-flow regression does not complete any of the 1,058 calculation proxies. See the validation review for exact checks.


## Current integrated execution replay

### Latest implementation continuation checkpoint

The full replay was repeated after adding source-denominator product parsing for explicitly listed quantity inputs and constraining generated integer smoke inputs to each field's declared range. Current result: 498 basic passes, 226 failures, 332 unsupported-calculator skips, and 2 exclusions; 724 records were selected for the calculator families, of which 663 entered a calculator function after 61 preflight stops. Compared with the preserved fresh baseline of 475/249/332/2, exact IDs show 24 fail-to-pass transitions and 1 pass-to-fail transition, for a net +23 passes. Unsupported/excluded totals are unchanged. The pass-to-fail record, common 6-2-5 mechanical splice, is now correctly blocked because the adjustment semantics remain unsupported; it was not forced through. This status partition does not establish calculation accuracy.

Focused source-aware unit/calculator checks are 44/44. Five item-level source slices compare selected numeric rates/results, units, and citations or source-driven blocks across 1-4-3, 10-3-1, 3-6-1, 2-4-8, and the unit-rate/compound denominator in 8-2-27. The 8-2-27 total quantity application and installation/dismantling table are still outside that check. Full section-rule verification remains incomplete, and the unsupported-family queue has not been classified item by item. Current machine evidence, exact transition IDs, and code/output hashes are in evals/runtime_validation/integration-replay-continuation-v4.json.

The current runner input recipe is synthetic spec-derived smoke input, not observed site conditions. It uses only the two existing functions `adjusted_daily_crew` and `per_unit`, at most 64 combinations per item, and the explicit basic pass criterion documented in the validation review. The complete 1,058 proxy partition is 475 basic pass, 186 calculator/rule-gate fail, 52 format/citation preflight fail, 11 source-alignment preflight fail, 332 no-compatible-calculator skips, and 2 misfiled exclusions. The historical 339 failure crosswalk is 94 pass / 243 fail / 2 unsupported. The historical 337 unassessed crosswalk is 5 source preflight / 330 unsupported / 2 misfiled. Among 382 historic passes, 381 remain pass and 1 now fails source alignment.

The fresh source validation also flags stale draft chunk hashes on all 1,058 entries against the current parse bundle, 100 citation-issue entries, and one format-issue entry. This is provenance/authoring work, not a successful rule check. Full table-note/reference verification remains 0, and all-condition accuracy remains unverified. Exact IDs and hash-pinned result are in `evals/runtime_validation/integration-main-execution-replay-2026-10-18.json`; prior executable output was preserved in `tmp/pre-replay-executable-20261018.json`.

### Replay follow-up after shared source-cell diagnostic fix

The full same-runner replay was repeated after changing how the shared `adjusted_daily_crew` calculator reports nonnumeric source cells. Counts are unchanged: 475 basic pass, 186 calculator/rule-gate failures, 52 format/citation failures, 11 source-preflight failures, 332 unsupported-calculator skips, and 2 exclusions. The two reproduced dash cells now fail as `unresolvable` with their exact source cell and citation; no rate was inferred. A selector-axis normalization audit found no unique enum-to-axis matches that would justify a general fuzzy selector patch. Remaining selector failures require explicit source/spec/parser corrections, and unsupported calculation families remain work to implement through shared expression coverage. Neither finding reduces the all-standards target or changes accuracy/full-rule counts (both remain 0). Machine evidence includes the current output hash and the two exact failures.
