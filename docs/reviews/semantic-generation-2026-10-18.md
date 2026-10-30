# Semantic generation review — 2026-10-18

## Real model result

The real request path used the existing Vertex AI Express Mode adapter, configured model `gemini-3.1-pro-preview`, LOW thinking, `response_json_schema`, a 7,000-token output limit, and SDK retries disabled. The preflight counted the PDF, prompt, and a conservative schema allowance before reserving the request. Three requests were made (generation-7 through generation-9); each finished with `STOP`, so the response was complete rather than truncated. Answer-token counts were 1,412, 793, and 796; reasoning-token counts were 0. The paid run produced no valid candidate and did not reach candidate execution, private final evaluation, or the temporary chat/aggregate/XLSX connection check.

The first semantic response violated the intended policy-reference contract by encoding the registered height policy as an ordinary `multiply_output` rule, with an empty `when` and an identity value. Subsequent responses repeated the policy/note interpretation failure. These are semantic-contract failures, not response truncation. The historical result and raw responses are retained in `evals/runtime_validation/gemini_6_1_4_2026-10-17/module-json-semantic-run-result.json` and `module-json-raw/generation-7.json` through `generation-9.json`.

The post-run code review also found that the policy registry's note anchor had replacement characters where the source bundle uses the Korean division name. The anchor was corrected in `backend/agent/tools/calc/policies.py`; historical attempt records were not rewritten. This code-side mismatch is distinct from the model's formula rewrite.

## Offline checks

`evals.test_calculation_modules` passes 29 tests with one environment-dependent skip. It replays the saved malformed semantic response and rejects it; retains rejection of the prior linear/simple height formula, including a negative multiplier above 40 m; verifies registered policy reference scope/source/version; assembles a mocked semantic candidate; and runs that candidate through the existing constrained interpreter at 7.001 m, 40.001 m, and the roof combination. These are offline/mock results and do not count as model-generation performance.

## Budget reconciliation

The cumulative authorization remains 9 generation/repair calls and USD 1.00. All 9 calls are recorded. The ledger reports historical per-request maximum reservations of USD 1.334004 (released as requests settled), a token-usage cost estimate of USD 0.64914, zero unsettled reservation, and USD 0.35086 remaining under the aggregate cap. The usage estimate is not an invoice; billing has not been verified. No further generation call fits the unchanged call-count authorization.

## Remaining work

The current semantic-generation path has not demonstrated real-model candidate success. The tested semantic case is the scoped formwork rule only; labor quantity, equipment hours, and other calculation types have not been generated or independently evaluated in this run. A valid candidate is still required before checking generated-candidate chat, edit, aggregate, and XLSX integration. Broader source-note interpretation, target/unit matching to each existing calculator, and robust model compliance with policy references remain common gaps for scaling to all estimate sections.
