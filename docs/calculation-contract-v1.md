# Calculation contract v1.0

This contract is additive to the existing estimate-spec JSON. Existing fields (`inputs`, `tables`, `crew_rules`, `quantity_model`, `blocked`, `cost_rules`) remain valid. New generated candidates must carry `calculation_contract`; previously registered modules remain readable during migration.

```json
{
  "calculation_contract": {
    "contract_version": "1.0",
    "source": {
      "edition": "2026",
      "pdf_sha256": "<sha256 of original source PDF>",
      "pages": [{"pdf_page": 193, "printed_page": 137}],
      "citations": [{"section_no": "6-3-1", "marker": "비고", "table_id": "p193-t0"}],
      "note_rule_map": [{"note_id": "p193-t0-note-1", "rule_ids": ["height-output"]}]
    },
    "site_inputs": [{"name": "height", "type": "positive_rational", "unit": "m", "source": "field fact"}],
    "application": {
      "conditions": ["..."],
      "target": {"name": "daily_output", "unit": "m3/day"},
      "order": ["..."],
      "system_policies": []
    },
    "executor": {"kind": "json_interpreter", "module_version": "1.0.0"},
    "verification": {"cases": [{"id": "...", "citation": "..."}]}
  }
}
```

`source_hash` on the module must equal `source.pdf_sha256`. `note_rule_map` preserves one-to-many traceability for calculation-related notes; a source bundle contains the complete parsed section, full section PDF pages, printed/PDF page mapping, and referenced clauses. The model cannot author independent expected answers: expected values reside in case files and are evaluated by the project calculator.

Rules and system assumptions are separate. A rule may refer only to policy IDs explicitly authorized for its division/section. `require_field` may ask for a missing site fact. Candidate validation rejects user inputs that request a calculation rate, interval count, accumulation method, or source document. `ask_policy` remains accepted only when reading legacy registered JSON; new candidates cannot emit it.

`executor.kind` is `json_interpreter` for the bounded declarative evaluator or `isolated_python` for a candidate that has passed sandboxed execution tests. Python candidates are explicitly registered in `data/calculation_modules/approved/python-registry.json` only after authoring and withheld evaluations pass for the same code hash and a human reviews the v1 contract. Local runtime uses digest-pinned Docker with no network, a read-only filesystem, no capabilities, an unprivileged UID, CPU/memory/process limits and a timeout. A deployed backend can use the private Cloud Run sandbox service interface in `deploy/calculation_sandbox/` with Cloud Run sandbox launcher enabled. That service is not deployed or verified here. AST checks are not treated as a sandbox.

Legacy records without `calculation_contract` remain loadable but are not valid inputs to the new authoring pipeline. No legacy registered record is silently promoted or rewritten.
