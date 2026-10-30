# 6-3-1 Gemini live trial

**Outcome:** one Gemini generation request completed and returned a candidate. The candidate remains a review-only draft; local checks and source review found unresolved items, so it is not ready for promotion.

## Run record

- Model: `gemini-3.1-pro-preview` through Vertex API, using the existing `VERTEX_API_KEY_BULK` setting. The key was never printed.
- Trial type: guided pipeline integration. The prompt explicitly supplied the source conditions and known uncertainties, so this was not a blind test of whether the model could discover those rules unaided.
- Generation requests: **1**. SDK retry attempts were configured as 1; no alternate model or second generation was used.
- The first `count_tokens` preflight failed with `ConnectError` before any generation. Its record is preserved at `tmp/refine-6-3-1-review/live_trial_run-count-preflight-failed.json`. A later authorized run with network access passed preflight and completed the one generation request.
- Successful preflight: 21,007 input tokens; output cap 16,384; estimated maximum cost USD 0.37894 using the configured estimated rates.
- Actual response usage metadata: 20,895 prompt tokens, 4,272 candidate tokens, 6,087 thought tokens, 31,254 total tokens. Full provider metadata is saved in `tmp/refine-6-3-1-review/raw_usage.json`; raw response is preserved in `tmp/refine-6-3-1-review/raw_response.txt`.
- Estimated cost at input USD 4/M and output USD 18/M: USD 0.160476 if priced on prompt plus candidate tokens, or USD 0.270042 if thought tokens are also charged at the output rate. These rates are estimates, and neither figure is a guaranteed bill or billing cap.
- Bundle SHA-256: `1d2ce86af110066d4691f2db74e0b6ffae93b3f57e824487e4e86116d42c8e3f`. Source excerpt SHA-256: `f7e84d8accb3e85f641258015bf0849a0bf4070d33d9d73ca3e4fa950044756d`.
- Output cap was set in the trial-only config at `tmp/refine-6-3-1-review/live-trial-config.json`. The repository-wide model config was not changed.

## Candidate against the source

The PDF excerpt and parsed text both place the installation and dismantling rules on PDF index 193, printed page 137. Their rule text agrees. The bundle manifest warns that the pre-existing draft's `source_pages` values 135–137 are printed page numbers, corresponding here to PDF indices 191–193.

| Rule | Source requirement | Candidate result |
|---|---|---|
| Height adjustment | Only when lifting equipment is not used and vertical height exceeds 7 m; for each 3 m, construction output is reduced by up to 9%. This changes construction output, not the physical work quantity. | The candidate states both conditions, quotes the source, and leaves the actual rate and treatment of a remainder under 3 m unresolved. Its blocker is in prose only: `blocked[0]` has no `blocked_if`, so execution cannot rely on it for automatic blocking. The candidate also says “최대 9%까지 … 감산해야 하나” (“must reduce by up to 9%”); the following clause says 9% is not fixed. The original validator treated the mandatory wording as a fixed-rate claim even with “up to” in the same sentence. |
| Regular crane use | Add the crane to the work crew when site conditions require regular use; do not reduce construction output. | The candidate preserves the equipment addition and no-reduction rule with a matching citation. It leaves the crane specification unresolved. |
| Roof slab | For roof-slab installation below 20 degrees, reduce construction output by 17%. This is a separate rule. | The candidate preserves the 20-degree condition and 17% as a separate adjustment. It marks the case blocked because the current calculation model does not support the adjustment; it does not combine this with the height rule. |
| Page mapping | PDF index 193 is printed page 137. | `draft.source_pages` uses PDF indices 191–193, which is correct for this field. Several human-readable `source` strings say “PDF 137쪽”; that is the printed page number and remains ambiguous unless called “인쇄 쪽.” |

The candidate file is `tmp/refine-6-3-1-review/candidate.json`. The first validator output, including its original 9% false positive, remains preserved at `candidate.review.json` and is reflected in the initial run record.

## Follow-up validation and review

I made a narrow validator improvement in `pipeline/refine_spec_rules.py`: a same-sentence “up to / maximum” phrase now prevents the 9% fixed-rate check from flagging the candidate, and blocked entries with a condition but no machine-readable `blocked_if` receive an explicit warning. The generated candidate and first validator result were left unchanged. A follow-up validation was saved separately as `tmp/refine-6-3-1-review/candidate.reviewed.report.json`.

The follow-up has **no validation errors**, 11 matching citations, and `original_draft_unchanged: true`. It remains `needs_human_review` because three open questions remain and it warns that `blocked[0]` is not machine-executable. This distinction matters: the candidate explains why calculation should stop, but its first blocker does not encode the stop condition in a field the runtime can evaluate. The candidate remains blocked pending proper unresolved-rule handling; this is not a production readiness pass.

The validator change was not followed by a full test-suite run. The candidate validation above is the only post-change check performed.

## Original source integrity

Current hashes match the supplied bundle manifest:

- Standards PDF: `cc226366b633a4e7d479ee55298318d9959dc988a910875c2ee775d958ee944b`
- Existing 6-3-1 draft: `e306258f9a1f729c53c7202298c795e7274b26cab329e3657577b6a3b82282d9`
- Parsed chunks: `0ec24a40650b1ceb4ef0e5fc82973aff07bfd35add8f0e31698bc267d39a4529`

No commit, push, deployment, or database operation was performed.
