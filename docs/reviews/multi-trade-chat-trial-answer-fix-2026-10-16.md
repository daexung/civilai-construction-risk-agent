# Local item-labor answer fix — 2026-10-16

## Cause and fix

The exact cached query reached candidate `6-4-1`; answering it entered labor calculation and raised `FileNotFoundError` because citation lookup still pointed at the worktree's absent `data/processed/page_map.json`. The earlier checker set the original source root's citation paths, but the running trial app did not. In local trial mode, the API now derives that root from `KNOWLEDGE_ASSET_DIR`, uses its existing page map, PDF, and chunks, and clears citation caches. No source assets were generated.

## Verification

The bounded loopback HTTP reproduction returned 200 for analyze, confirm, search, the `6-4-1` answer, estimate, and XLSX. Search reported a cache hit and `api_calls: 0`; embedding calls are guarded to fail. The answer was `CALCULATED` with no pending questions. The estimate was `PARTIAL`. The XLSX was saved under ignored `.trial/`, passed ZIP integrity checks, and opened with `openpyxl`.

## Limits

Uncached/new questions still stop at cache miss without embedding. The aggregate estimate is partial, and the operating database was not verified.

## Reproduction

From the worktree root:

```powershell
$env:PYTHONPATH="$PWD;C:/Users/user/Desktop/PROJECTS/civilai-construction-risk-agent/.venv/Lib/site-packages"; $env:PYTHONIOENCODING='utf-8'; $env:LOCAL_TRIAL_ITEM_LABOR='on'; $env:AGENT_OFFLINE='1'; $env:AGENT_LLM='off'; $env:KNOWLEDGE_ASSET_DIR='C:/Users/user/Desktop/PROJECTS/civilai-construction-risk-agent/data/knowledge'
& 'C:/Users/user/Desktop/PROJECTS/civilai-construction-risk-agent/.venv/Scripts/python.exe' -B -u evals/repro_item_labor_http.py
```

The script runs the local server on `127.0.0.1:8012`, captures no external model or embedding calls, and terminates the server when finished.

## Two-trade evaluation-question attempt

The two exact questions below were confirmed as cache-key matches before this attempt:

- `외벽에 방수모르타르를 15㎜ 두께로 바르려는데 ㎡당 미장공은 몇 인 들어?`
- `철판 두께 0.6㎜, 규격 400㎜짜리 스파이럴덕트를 해체하려면 m당 덕트공이 몇 인이야?`

The bounded request to the foreground trial API on `127.0.0.1:8011` joined those strings with ` 그리고 ` and called analyze. The analyzer returned four spans: the waterproof-mortar question (`unconfirmed`, suggested work `방수`), a separate `철판 두께 0.6㎜` span (`unconfirmed`, no work item), the remaining spiral-duct question (`unconfirmed`), and a `벽` background span. Since the unconfirmed steel-thickness span had no analyzer-suggested work to confirm, the reproduction stopped before confirm/search; no candidate or calculation was forced. The saved run output is `.trial-two-trade.stdout.log`; the reproduction is `evals/reproduce_cached_two_trade_trial.py`.

No external calls were made: analysis only was reached, and the already-running server was configured with `AGENT_OFFLINE=1` and `AGENT_LLM=off`. This attempt does **not** establish two-trade calculation. It establishes that these exact cached questions are currently split into spans the analyzer cannot safely confirm together, so a full multi-trade result remains unverified.

## Frontend verification limit

The focused frontend test could not start because Node reported `EPERM` while resolving its sandbox temporary path. The foreground CRA server on port `3012` compiled without TypeScript issues, but its one loopback HTTP check timed out. The browser surface also rejected the requested visibility capability. Per the run constraint, there was no further frontend/browser retry; the UI remains unverified. Port `3000` was not touched.

## Follow-up: completed two-trade HTTP workflow

The earlier two-question attempt above is preserved as its original incomplete result. This follow-up uses two other exact cache-hit evaluation questions with existing calculator specs:

- `시멘트 액체방수를 바닥에 300㎡ 바르려면 인력 품은 어떻게 잡아야 해?`
- `건물 기계실 배관 ø100㎜에 건물용 적산열량계를 설치하면 개당 배관공은 몇 인이야?`

The analyzer marked both full question spans `unconfirmed`. The evaluator explicitly confirmed `방수`, which the analyzer had proposed, and selected `건물용 적산열량계` from the second exact source span. The analyzer separately identified `바닥` and `300㎡`; those were retained as background and quantity conditions. Confirmation produced two independent items, and each `request_text` remained byte-for-byte the original evaluation question.

One bounded loopback HTTP run completed both local query-cache searches (`api_calls: 0`, cache hit for each), accepted only the exact supported specs, answered source-supported inputs, and calculated both items:

| Item | Selected spec | Confirmed inputs | Labor result |
| --- | --- | --- | --- |
| Cement liquid waterproofing | Architecture 6-4-1 | Floor, 300㎡ | Waterproofer 0.075 person/㎡; general worker 0.040 person/㎡ |
| Building heat meter installation | Mechanical 6-2-2 | ø100~125mm band from the stated ø100mm; 1 each from “per unit” | Plumber 0.569 person/each; general worker 0.569 person/each |

The combined estimate included both items and returned `PARTIAL`: direct total 7,782,586 KRW (waterproofing 7,537,800 KRW; meter 244,786 KRW). Material costs remain uncalculated under the specs, so this is not a complete contract amount. The exported workbook returned HTTP 200, passed ZIP integrity checks, opened with `openpyxl`, and its detail sheet contained both item descriptions. The artifact is `.trial/multi-trade-two-calculated-items.xlsx`.

The server ran with `AGENT_OFFLINE=1` and `AGENT_LLM=off`; embedding and client creation functions were patched to raise if called. No external model, embedding, or database calls were made. The saved reproduction is `evals/reproduce_cached_two_trade_trial.py`; it owns its local server, separates server stdout/stderr logs, and has a 52-second deadline. The spiral-duct demolition question was not substituted with an installation spec; this successful follow-up used the exact cached heat-meter installation evaluation question instead.
