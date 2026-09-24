"""One-time G7 run for the frozen second holdout, after human source review.

Use the existing P5 scoring implementation with separate inputs and outputs.
The original P5 report and raw extraction paths are never selected here.
"""

from common import RESULTS
import p5_eval


if __name__ == "__main__":
    run_dir = RESULTS / "holdout_v2_eval"
    if (run_dir / "p5_report.json").exists() or (run_dir / "raw").exists():
        raise SystemExit("Second holdout evaluation already started; refusing a second run")
    p5_eval.GT = RESULTS / "holdout_v2" / "ground_truth.json"
    p5_eval.RUN_DIR = run_dir
    p5_eval.main()
