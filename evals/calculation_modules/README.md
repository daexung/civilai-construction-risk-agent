# Calculation case sets

The authoring and final-evaluation catalogs are deliberately disjoint audit indexes spanning ratio adjustment, repeated intervals, crew changes, daily-output addition/subtraction, equipment time, and cost combination. Existing calculator paths are exercised by evals/test_calculation_modules.py and evals/check_estimate_tools.py; the final catalog is not supplied to a model.

The formwork_authoring_cases.json and formwork_final_evaluation_cases.json files are executable CLI case files for the 6-3-1 JSON module. The latter is passed with --evaluation-cases and is never included in model prompts. The source-based audit catalog should not be passed as a CLI execution file.


Cross-calculator mock regression: `evals/test_cross_calculator_offline.py` exercises source-backed `per_unit` and `adjusted_daily_crew` cases through `author_python_candidate`, contract validation, the actual digest-pinned Docker executor, one feedback repair, and separate final evaluation. Use the v3 per-unit sets (source applicability inputs added) and v2 post-equipment sets. The older versions remain preserved; all mock results are offline-path evidence, not actual model generation.
