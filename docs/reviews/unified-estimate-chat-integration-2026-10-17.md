# Unified estimate chat integration review — 2026-10-17

## Result

The shared chat flow supports one or several estimate items, combines item calculations and shared costs, exports the combined workbook, and applies a quantity edit to the selected item while retaining sibling state. The beta notice now describes multi-item estimates accurately.

## Changes

- Unified single-work and multi-work requests through the same scope, item calculation, aggregate and workbook flow.
- Kept item targeting through the child dialogue so sibling-preservation text does not redirect a selected edit. Pending-card references retain the conversation revision.
- Normalized public card fields for one-item conversations and preserved the existing API shape.
- Made the dialogue evaluation's optional source-data directory configurable with `CIVILAI_SOURCE_DATA`; the default is the repository's `data` directory, and absent artifacts are not assigned as citation paths.
- Reconciled the beta notice with currently supported multi-item estimates.

## Validation

- `evals/check_unified_estimate_chat.py` passed, including the exact follow-up `수성페인트 롤러칠 면적만 120㎡로 변경해줘. 셔터 조건과 수량은 그대로 유지해줘.` and sibling-state assertions.
- `evals/check_dialogue.py` passed with the existing Python 3.14 environment and `CIVILAI_SOURCE_DATA` pointed at the read-only source checkout data directory. No model, embedding, remote database or trial API was used.
- `frontend/npm run build` passed and prerendered the application. Existing dependency and lint warnings remain.
- The focused `BetaNotice.test.js` could not be discovered by the linked React Scripts/Jest setup, which reported zero matching tests despite the file being present. No dependency install or test-runner reconfiguration was made.
- `git diff --check` passed.

## UI and workbook evidence

The final model-off UI review used a 100㎡ paint item and a two-unit shutter item from local test rates. Updating paint to 120㎡ preserved the shutter's selected specification, quantity and calculated result. The combined VAT-inclusive total changed from ₩4,821,789 to ₩5,094,969. The latest, earlier-button and refreshed workbook files agree on paint direct cost ₩872,400, shutter direct cost ₩1,839,464, and one aggregate indirect-labor row of ₩465,282.

The checked files are `docs/reviews/evidence/unified-estimate-ui-2026-10-17/16-review-baseline100.xlsx`, `17-review-latest120.xlsx`, `18-review-earlier-button120.xlsx`, `19-review-refreshed120.xlsx`, `19-review-refreshed120.png`, and `20-sol-final-xlsx-reconciliation.json`. These contain only the local test estimate and review evidence.

## Limits

Local legacy retrieval did not resolve the indoor-waterproof request, so the UI evidence uses shutter installation and paint. This does not establish waterproof retrieval. Member persistence, production retrieval, and real-model behavior after the final item-edit fix were not tested. The paint item remains a partial estimate with disclosed exclusions, and these local rates are test values rather than market prices. The final edit was model-off; no new model calls were made, and the recorded earlier usage remained 5 turns / 12 calls / $0.00714362.

## Release state

This review records the code and local evidence before merge. The merge commit, backend Actions run, Vercel deployment, and live readiness/version checks are recorded separately after the approved production rollout completes.
