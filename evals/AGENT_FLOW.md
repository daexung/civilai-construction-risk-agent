# Agent Flow Map

This document records the current graph and state contracts used by the eval
runner. It is intentionally descriptive only; it does not change agent behavior.

## Entry Points

- API entry: `api/routers/chat.py`
  - `chat()` loads previous conversation messages, appends the latest user
    message, then calls `graph.stream(..., stream_mode="values")`.
  - It stores `final_response` and `structured_response` from the last graph
    event.
- CLI/dev entry: `agents/router/chat.py`
  - Calls `graph.invoke({"messages": history, "project_id": "PJT-001"})`.
- Graph entry: `agents/router/graph.py`
  - Exposes `graph = build_graph()`.

## Graph Shape

```text
START
  -> router                          # classify_question: intent + domains + missing_for_cost
      -> END                         # blocked / OUT_OF_DOMAIN immediate answer
      -> synthesize                  # CHAT / LOOKUP / CLARIFY / REPORT-with-empty-domains
      -> extractor                   # REPORT route
  -> extractor                       # fill state['inputs']; decide weather_skip
      -> weather                     # needs_weather and not weather_skip
      -> equipment/material/labor    # dynamic Send based on target_agents
      -> aggregator                  # no cost targets
  -> weather
      -> equipment/material/labor    # dynamic Send based on target_agents
      -> aggregator / synthesize     # on weather-only or failure
  -> equipment/material/labor
      -> aggregator
  -> aggregator                      # merge domain results into aggregated_result
      -> synthesize
  -> synthesize
      -> END
```

Router intents (`agents/router/router.py`): `OUT_OF_DOMAIN`, `CHAT`, `LOOKUP`,
`CLARIFY`, `REPORT`. Only `REPORT` (with non-empty `domains`) reaches
`extractor`; others resolve at `router` (END) or `synthesize`. When
`missing_for_cost` is non-empty the cost domains are dropped and only
`weather` runs (partial report).

## State Keys

`RiskState` is declared in `agents/router/state.py`.

| Key | Producer | Consumer | Meaning |
| --- | --- | --- | --- |
| `messages` | API/CLI, every node | all nodes | LangChain message history. |
| `project_id` | API/CLI | `weather_node` | Project lookup key for weather risk. |
| `intent` | `router_node` (`classify_question`) | routing, `synthesize_node`, UI | `OUT_OF_DOMAIN`, `CHAT`, `LOOKUP`, `CLARIFY`, `REPORT`. |
| `domains` | `router_node` | `extractor_node`, routing | Domains needed for a REPORT: `weather`/`equipment`/`material`/`labor_cost`. |
| `missing_for_cost` | `router_node` | `extractor_node`, `synthesize_node` | Missing cost inputs → drop cost domains, run weather only (partial report). |
| `inputs` | `extractor_node` | weather/cost agents, `synthesize_node` | Structured inputs (quantity, unit, prices, contract_type, workers, duration_days, location, work_type, ...). |
| `weather_skip` | `extractor_node` | `synthesize_node` | Work type not supported by weather analysis → skip `weather_node`. |
| `answer_type` | `router_node`, inferred by `synthesize_node` | `synthesize_node`, UI | Legacy: `CHAT`/`RAG_QA`/`COST_REPORT`/`RISK_REPORT`/`MISSING_INFO`. |
| `question_type` | `router_node` | `synthesize_node` | Legacy: `A` weather route, `B` non-weather route. |
| `needs_weather` | `router_node` | `extractor_node`, `weather_node` | Whether weather analysis is required. |
| `target_agents` | `router_node` | `extractor_node`, `weather_node` | Cost agents to call. |
| `rag_result` | `router_node` LOOKUP helper | `synthesize_node` | Structured RAG/price lookup result. |
| `rag_response` | optional RAG path | `synthesize_node` | Textual RAG response. |
| `weather_response` | `weather_node` (or `extractor_node` on `weather_skip`) | `aggregator_node`, `synthesize_node`, cost agents | JSON string from weather risk service. |
| `weather_result` | `weather_node` | `aggregator_node`, `synthesize_node` | Normalized weather risk dict. |
| `equipment_response` / `equipment_result` | `equipment_node` | `aggregator_node` | Raw text / normalized equipment cost dict. |
| `material_response` / `material_result` | `material_node` | `aggregator_node` | Raw text / normalized material cost dict. |
| `labor_cost_response` / `labor_cost_result` | `labor_cost_node` | `aggregator_node` | Raw text / normalized labor cost dict. |
| `aggregated_result` | `aggregator_node` | `synthesize_node` | Merged domain results in a common schema. |
| `final_response` | `router_node` for immediate exits, `synthesize_node` normally | API/UI/evals | User-visible answer. |
| `structured_response` | `synthesize_node` | API/UI/evals | Card-ready structured answer. |

## Structured Result Fields Used By Synthesis

Each cost agent result is expected to expose:

- `cost_items`
- `total_cost`
- `calculation_details`
- `evidence`
- `assumptions`
- `missing_info` or `missing_fields`
- optional summary fields such as `risk_level`, `expected_delay`, `main_cause`

`synthesize_node` merges those into:

- `summary.total_additional_cost`
- `summary.risk_level`
- `summary.expected_delay`
- `summary.main_cause`
- `cost_breakdown`
- `calculation_details`
- `evidence`
- `assumptions`
- `missing_info`

## Evaluation Boundary

The eval runner treats the public graph output as the system under test:

- input: one user question plus `project_id`
- output: `final_response`, `structured_response`, and selected final state keys
- scoring: strict keyword/forbidden phrase checks plus structured summary and
  numeric expectation checks where applicable


