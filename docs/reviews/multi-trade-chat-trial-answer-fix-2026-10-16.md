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
