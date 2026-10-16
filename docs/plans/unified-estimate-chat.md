# Unified estimate chat design

## Goal and boundary

Use the existing `/chat` → `/api/chat` conversation for estimates with either one work item or several. Both counts follow the same scope confirmation, item search, input, calculation, and estimate path. General construction Q&A and the existing authentication, usage, ownership, guest/member history, checkpoint, run-trace, and workbook paths stay on their current services. Do not expose the localhost item-labor trial API or depend on its pinned query cache.

## Request and state flow

1. Dispatch estimate intent to the existing Dialogue service from `/api/chat` regardless of item count or `AGENT_MODE`; leave non-estimate Q&A on its current graph. `_uses_dialogue` must continue already-saved graph conversations on their original graph while routing new estimates to the unified path. Reuse the conversation's existing thread/conversation ID, checkpoint, request idempotency, usage accounting, and answer trace. There is one saved execution and one shared per-turn model/tool budget.
2. Analyze the original request once with `scope.py`. Return scope questions in the normal chat response. Only an explicit work choice creates an item. Keep background, quantity, conditions, and exclusions as their own span types. Attach a condition/background to a work only when the source links it unambiguously; otherwise ask which item it belongs to. Confirmed work spans become one `EstimateSession` with stable IDs derived from source spans and an explicit `item_order`.
3. Keep one session in `DialogueState`; add an active/target `item_id`. Pass it to every item-scoped `tools.py` operation instead of relying on `tools._item(session)` selecting the first row. Use the existing `backend.agent.nodes.retrieve` → `backend.knowledge.runtime` production search path. Do not route through `local_v1_search` or the 127-row trial cache.
4. Scope every pending item question by `(item_id, field, version)` in its stable `ref` and answer key. A reply must match the current item and version. Preserve the old bare-field reference for restored single-item checkpoints. This also makes `free_card_answer` lookup unambiguous: if a field/ref cannot map to exactly one pending item question, require a normal charged turn. For a follow-up message that could change more than one item, ask the user to choose the item before applying it.
5. An item edit updates that item in place and invalidates the shared estimate and export. It preserves other item IDs, conditions, results, and order. Run common-condition resolution and the cost statement once over all priced items. If any item is still awaiting scope, search, or input, keep the estimate pending; if settled items coexist with unpriced/unsupported work, show a clearly labeled partial estimate and its omitted items.
6. Adapt the single-item response fields for a one-item session so existing chat cards and exports remain compatible. Add an item list to the same response for multiple items; render the same inline chat, question, and download controls rather than a separate mode/tab. Export remains `/api/export/{thread_id}.xlsx` and uses the one current checkpoint.

## Likely change points

- `backend/api/main.py`: route estimate intent into Dialogue while retaining the current QA graph, request claims, usage limits, identity checks, and `/api/export`.
- `backend/api/dialogue_service.py`: map a multi-item session to the existing response contract, restore it, and export only a current combined estimate.
- `backend/agent/estimate/dialogue.py`: scope confirmation, item targeting, per-item pending questions, turn planning, and shared request budget.
- `backend/agent/estimate/scope.py`: produce a confirmed N-item plan without converting conditions/backgrounds into work or guessing cross-item ownership.
- `backend/agent/estimate/state.py`: preserve stable item IDs/order and question identity across changes and checkpoint restore.
- `backend/agent/estimate/tools.py`: make item-scoped operations accept an explicit ID while retaining first-item compatibility for legacy single-item callers; reuse production retrieval.
- `backend/agent/estimate/aggregate.py`: aggregate shared costs once, retain pending versus partial distinctions, and list unpriced items.
- `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/components/ChatArea.tsx`, and `frontend/src/components/UserQuestion.tsx`: carry item-scoped refs and show several item cards/questions in the existing chat. `ChatApp.tsx` storage remains one conversation/thread with its current member/guest ownership rules.
- Focused tests under `evals/` for scope, dialogue transitions, API ownership/checkpoints, aggregate/XLSX, and frontend chat rendering.

## Runtime defaults and limits

The unified estimate route is selected by estimate intent, not by an opt-in trial endpoint or a split single/multi mode. Production's current `AGENT_MODE` gate and deployment workflow must not silently leave new estimates on the legacy single-item graph. After implementation checks pass, set the production default/configuration for the unified Dialogue path and validate it at startup; keep existing saved graph conversations readable and resumable. Do not change the live deployment in this design phase. The existing per-turn budget (6 planning attempts, 4 tool calls, 25 seconds) is shared across all items and is never reset per item. If it runs out, checkpoint completed work and leave the rest pending for a later turn.

## Core checks

- One item uses the same `/api/chat` path, answer, pricing, checkpoint restore, and workbook as before.
- Two or more distinct items retain source order and stable IDs; each item retrieves through `backend.knowledge.runtime`, gets only its own confirmed inputs, and contributes to one cost statement/export.
- Background/condition/exclusion spans never become work; ambiguous condition ownership asks a question. A follow-up targeting multiple items asks which item. Stale or cross-item refs are rejected.
- Editing one item invalidates the aggregate/export but leaves every other item's state intact. Pending, unsupported, and partial states are distinct and disclose unpriced scope.
- Existing non-estimate QA, member/guest storage, owner checks, usage/idempotency, execution trace, checkpoint recovery, and XLSX download remain covered.

## Main risks

Old checkpoints contain one-item sessions and unscoped field refs, so restore needs a compatibility path without rewriting saved history. Multi-item condition assignment is the main correctness risk: uncertain ownership must block only the affected calculation and must never silently attach to another work. `free_card_answer` currently indexes pending answers by field name, which collides when two items ask the same field; the composite question key must be used before enabling free multi-item answer turns. A single request can multiply retrieval/tool cost; the shared budget must cap the whole turn. Larger checkpoints increase stored state, so retain existing item limits and avoid logging full input/credentials/member data. Partially priced work must not appear as a complete contract amount or allow a stale workbook download.
