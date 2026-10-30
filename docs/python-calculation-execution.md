# Isolated Python calculation modules

## CLI modes

`pipeline.calculation_modules` defaults to `json_interpreter`. Select
`--executor isolated_python` explicitly to generate Python. The Python author
receives source evidence and the case's `spec` plus site `inputs`; the trusted
parent compares the result to `expected`. Expected values and final evaluation
cases are never written into the mounted sandbox payload. Repair feedback names
only failed output fields, not reference or candidate values. Candidate syntax
and basic input dependence are checked, but static checks cannot prove semantic
correctness. Hidden, varied cases and review are still required.
Contracted Python generation refuses an authoring suite unless at least two
different site-input sets produce different expected output values. This
prevents a single-case constant result from serving as a passing calculation;
the separate withheld cases add another check.
Python generation returns code and a v1 contract together; the code, matching
`.contract.json`, authoring record and withheld evaluation record are retained
only after both test sets pass. Registration requires the same reviewed
contract and source section/version as those candidate artifacts.

The isolated Python sequence is: candidate generation, resource-limited
container execution, at most two repair attempts, withheld final evaluation,
candidate-file storage, explicit registration, then estimate execution. A
candidate is not successful unless generation and its tests actually ran and
passed. A final-evaluation failure is retained as unreviewed and cannot be
registered through the normal review flow. The separate registration command
requires an operator-selected contract and image digest; it does not infer
approval from a passing test.

Example local generation (replace the digest with the result of inspecting the
pulled image; do not pass a mutable tag):

```powershell
docker pull python:3.12-slim
$image = docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
$image
$pdf = Get-ChildItem data\raw\standard_estimation\*.pdf | Select-Object -First 1 -ExpandProperty FullName
.\.venv\Scripts\python.exe -m pipeline.calculation_modules `
  --source $pdf --section-no 6-3-1 --division 공통 `
  --cases evals\calculation_modules\formwork_authoring_cases.json `
  --evaluation-cases evals\calculation_modules\formwork_final_evaluation_cases.json `
  --executor isolated_python --sandbox-image $image --call-model `
  --max-calls 3 --token-budget 12000 --max-usd 0.25
```

The command above makes paid model calls. Python mode allows at most three
requests (initial generation plus two repairs). At the configured standard
global rates, a 12,000-token reservation costs at most $0.144 at token prices;
`--max-usd 0.25` is an additional per-run guard. These are configured
reservation limits, not a guaranteed invoice ceiling: confirm the actual
Vertex endpoint, model availability, billing SKU and regional pricing before
running. Each request uses provider `countTokens` for its exact input, reserves
the full output allowance, and cannot retry implicitly. An ambiguous response
still consumes the reserved call, tokens and cost allowance. For existing
candidates, review the source, final evaluation and contract, then register
explicitly:

```powershell
.\.venv\Scripts\python.exe -m pipeline.calculation_modules `
  --register-candidate data\calculation_modules\candidates\python\candidate.py `
  --registration-contract path\to\reviewed-contract.json `
  --module-id reviewed-module --module-version 1 `
  --sandbox-image $image --division 공통 --section-no 6-3-1
```

Do not register until the generated candidate has passed the isolated tests and
the withheld evaluation, and the exact registered source hash has been reviewed.

## Isolation boundary

The local runner requires an already available Docker image identified by an
immutable SHA-256 digest. It runs with networking disabled, a read-only root,
no Linux capabilities, non-root UID, process/memory/CPU limits and a timeout.
Only candidate source and the two operational objects (`spec`, `inputs`) are
mounted. Expected outputs remain in the trusted process. Docker is fail-closed:
there is no host-Python fallback and no automatic image pull.

## Deployment status and required architecture

The checked-in production deployment is a single Cloud Run API container
(`Dockerfile`, `deploy/run_api.py`). It has no Docker Engine or Docker socket,
so the local Docker runner cannot execute in the deployed API. A separately
deployable private worker now exists in `deploy/calculation_sandbox/`; the API
client dispatches registered code to it when `CALC_PYTHON_SANDBOX_URL` is set
and authorizes the request with a Cloud Run ID token. The worker passes only
candidate source and operational `spec`/`inputs` through read-only mounts to
`sandbox do`, with network egress disabled by default, output limits, a wall
timeout and shell CPU/address-space limits.

Deploy the worker as a separate Cloud Run service using second-generation
Cloud Run Sandboxes (the code-execution feature is currently Preview). Set
`--sandbox-launcher`, keep it private (`--no-allow-unauthenticated`), use a
dedicated worker service account with no data/API permissions, set concurrency
to 1 and a small maximum instance count, and grant `roles/run.invoker` only to
the existing API service account. Set `CALC_PYTHON_SANDBOX_URL` on the API to
the worker's HTTPS base URL; optionally set `CALC_PYTHON_SANDBOX_AUDIENCE` to
the exact Cloud Run audience. The implementation uses Google's documented
`sandbox do` process interface and service-to-service ID-token authentication.
Cloud Run sandboxes isolate the worker child from the parent workload's
environment, secrets and metadata service, and block outbound traffic by
default. [Cloud Run code execution](https://docs.cloud.google.com/run/docs/code-execution),
[sandbox configuration](https://docs.cloud.google.com/run/docs/configuring/services/sandboxes),
[service-to-service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).

Operator deployment outline (replace project, region, repository, service
accounts and the worker URL; these commands were not run):

```bash
docker build -f deploy/calculation_sandbox/Dockerfile \
  --build-arg BASE_IMAGE=python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  -t REGION-docker.pkg.dev/PROJECT/REPOSITORY/calc-sandbox:VERSION .
docker push REGION-docker.pkg.dev/PROJECT/REPOSITORY/calc-sandbox:VERSION
gcloud beta run deploy calc-sandbox \
  --image REGION-docker.pkg.dev/PROJECT/REPOSITORY/calc-sandbox:VERSION \
  --region REGION --execution-environment gen2 --sandbox-launcher \
  --no-allow-unauthenticated --concurrency 1 --max 2 --cpu 1 --memory 1Gi \
  --timeout 30s --service-account calc-sandbox-no-roles@PROJECT.iam.gserviceaccount.com
gcloud run services add-iam-policy-binding calc-sandbox --region REGION \
  --member serviceAccount:API_SERVICE_ACCOUNT --role roles/run.invoker
gcloud run services update API_SERVICE --region REGION \
  --update-env-vars CALC_PYTHON_SANDBOX_URL=https://WORKER_URL
```

The API service account needs `roles/run.invoker` on the worker. Grant no data
or model roles to the worker service account. The dedicated worker must be
load-tested for its per-instance shared CPU/memory budget and the Preview
feature's target-region availability before enabling Python modules.

No cloud service, IAM binding or API environment was created or changed in this
task. The private worker was not deployed or invoked, and Preview availability
must be confirmed for the target project/region. Therefore production Python
execution remains **not verified** until the service is deployed with the
required sandbox launcher and IAM, then exercised end to end. The current
serving image now includes approved JSON modules and runtime support code, so
the existing JSON interpreter path remains available without Docker.

## Model preflight and budget

The existing Vertex/Gemini adapter is retained. Before each generation request,
it calls the provider's `countTokens` endpoint for the exact PDF and prompt;
character-length estimates are not used as a token or cost guarantee. The
request reserves the complete remaining output allowance, including reasoning
tokens, against the per-run token and USD limits. SDK retries are disabled so a
single authorized attempt is not silently replayed. Response accounting uses
`prompt_token_count` and `candidates_token_count + thoughts_token_count`.

`pipeline/draft_specs_config.json` records the public standard-global rates
checked 2026-10-17 ($2/M input and $12/M output for Gemini 3.1 Pro Preview at up
to 200K input tokens). A configured run is still contingent on confirming the
actual Vertex region, endpoint, model availability, billing SKU and any tier
differences immediately before use. With a 12,000 combined-token budget and
four calls maximum, the configured token-price ceiling is $0.144 before any
non-token charges; the default `$0.25` USD cap is a second independent guard.
The exact preflighted input token count plus full remaining output allowance is
reserved before each billable call.

No paid model generation was run for this change. See Google's [Vertex AI
pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
[token-count API](https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/count-tokens),
and [usage metadata](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/GenerateContentResponse).
