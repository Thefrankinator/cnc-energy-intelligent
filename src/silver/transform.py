"""
Silver Layer -- CNC Energy Intelligence Platform
Validation, defect flagging, timestamp injection, missing-value handling.

Usage:
    python src/silver/transform.py

Reads:
    data/bronze/metadata/train.csv
    data/bronze/experiments/experiment_NN.csv  (x18)

Produces:
    data/silver/metadata/train_silver.parquet
    data/silver/experiments/experiment_NN_silver.parquet  (x18)
    data/silver/quality/quality_report_{run_id}.json
    data/silver/quality/quality_summary.csv
"""

import csv
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT     = Path(__file__).resolve().parents[2]
BRONZE_DIR       = PROJECT_ROOT / "data" / "bronze"
BRONZE_META      = BRONZE_DIR / "metadata" / "train.csv"
BRONZE_EXP_DIR   = BRONZE_DIR / "experiments"
SILVER_DIR       = PROJECT_ROOT / "data" / "silver"
SILVER_META_DIR  = SILVER_DIR / "metadata"
SILVER_EXP_DIR   = SILVER_DIR / "experiments"
SILVER_QUAL_DIR  = SILVER_DIR / "quality"
QUALITY_SUMMARY  = SILVER_QUAL_DIR / "quality_summary.csv"

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
EXPECTED_TRAIN_ROWS = 18
EXPECTED_TRAIN_COLS = 7
# The dataset has 48 source columns (not 53 as stated in the spec template --
# Z1 has no OutputPower column in this dataset).
EXPECTED_EXP_COLS = 48

VALID_TOOL_CONDITION       = {"unworn", "worn"}
VALID_FEEDRATE             = {3, 6, 12, 15, 20}
VALID_CLAMP_PRESSURE       = {2.5, 3.0, 4.0}
VALID_MACHINING_FINALIZED  = {"yes", "no"}
VALID_PASSED_INSPECTION    = {"yes", "no"}        # empty/NaN also allowed

# All known Machining_Process labels (spec baseline + observed extras)
VALID_MACHINING_PROCESS = {
    "Starting", "Prep",
    "Layer 1 Up", "Layer 1 Down",
    "Layer 2 Up", "Layer 2 Down",
    "Layer 3 Up", "Layer 3 Down",
    "Repositioning", "end",          # observed in dataset, not in spec baseline
}

POWER_COLS    = ["X1_OutputPower", "Y1_OutputPower", "S1_OutputPower"]
DEFECT_COL_FEEDRATE  = "M1_CURRENT_FEEDRATE"
DEFECT_COL_POSITION  = "X1_ActualPosition"
DEFECT_COL_PROGRAM   = "M1_CURRENT_PROGRAM_NUMBER"

# ---------------------------------------------------------------------------
# Logging helpers  (ASCII-only -- Windows cp1252 safe)
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def log_warn(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] WARN  {msg}")


def log_error(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] ERROR {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

def silver_is_fresh() -> bool:
    """Return True if all expected Silver outputs are newer than Bronze inputs."""
    bronze_files = list(BRONZE_META.parent.glob("*.csv")) + list(BRONZE_EXP_DIR.glob("*.csv"))
    if not bronze_files:
        return False
    latest_bronze = max(f.stat().st_mtime for f in bronze_files)

    silver_parquets = list(SILVER_EXP_DIR.glob("*.parquet")) + list(SILVER_META_DIR.glob("*.parquet"))
    if not silver_parquets:
        return False
    earliest_silver = min(f.stat().st_mtime for f in silver_parquets)

    return earliest_silver > latest_bronze


# ---------------------------------------------------------------------------
# Step 1 -- Schema validation
# ---------------------------------------------------------------------------

def validate_train(df: pd.DataFrame) -> list[dict]:
    """Validate train.csv schema. Returns list of rule result dicts."""
    results = []

    def rule(name: str, passed: bool, detail: str = "") -> dict:
        return {"rule": name, "passed": passed, "detail": detail}

    # Row / col count
    results.append(rule("train_row_count",
                         len(df) == EXPECTED_TRAIN_ROWS,
                         f"got {len(df)}, expected {EXPECTED_TRAIN_ROWS}"))
    results.append(rule("train_col_count",
                         len(df.columns) == EXPECTED_TRAIN_COLS,
                         f"got {len(df.columns)}, expected {EXPECTED_TRAIN_COLS}"))

    # Column No: integers 1..18, no dups, no gaps
    no_series = df["No"].dropna()
    no_vals   = sorted(no_series.astype(int).tolist())
    expected_no = list(range(1, EXPECTED_TRAIN_ROWS + 1))
    results.append(rule("train_no_range_nodups",
                         no_vals == expected_no,
                         f"got {no_vals}"))

    # Allowed-value checks
    bad_tool  = df["tool_condition"].dropna()[~df["tool_condition"].dropna().isin(VALID_TOOL_CONDITION)]
    results.append(rule("train_tool_condition",
                         len(bad_tool) == 0,
                         f"{len(bad_tool)} invalid values"))

    bad_feed  = df["feedrate"].dropna()[~df["feedrate"].dropna().astype(int).isin(VALID_FEEDRATE)]
    results.append(rule("train_feedrate",
                         len(bad_feed) == 0,
                         f"{len(bad_feed)} invalid values"))

    bad_clamp = df["clamp_pressure"].dropna()[~df["clamp_pressure"].dropna().isin(VALID_CLAMP_PRESSURE)]
    results.append(rule("train_clamp_pressure",
                         len(bad_clamp) == 0,
                         f"{len(bad_clamp)} invalid values"))

    bad_mach  = df["machining_finalized"].dropna()[
        ~df["machining_finalized"].dropna().isin(VALID_MACHINING_FINALIZED)]
    results.append(rule("train_machining_finalized",
                         len(bad_mach) == 0,
                         f"{len(bad_mach)} invalid values"))

    # passed_visual_inspection: yes / no / NaN allowed
    bad_insp  = df["passed_visual_inspection"].dropna()[
        ~df["passed_visual_inspection"].dropna().isin(VALID_PASSED_INSPECTION)]
    results.append(rule("train_passed_visual_inspection",
                         len(bad_insp) == 0,
                         f"{len(bad_insp)} invalid values"))

    # No fully null rows
    all_null_rows = df.isna().all(axis=1).sum()
    results.append(rule("train_no_fully_null_rows",
                         all_null_rows == 0,
                         f"{all_null_rows} fully-null rows"))

    return results


def validate_experiment(df: pd.DataFrame, name: str) -> list[dict]:
    """Validate a single experiment CSV. Returns list of rule result dicts."""
    results = []

    def rule(rname: str, passed: bool, detail: str = "") -> dict:
        return {"rule": rname, "passed": passed, "detail": detail, "file": name}

    # Not empty
    results.append(rule("exp_not_empty",
                         len(df) > 0,
                         f"{len(df)} rows"))

    # Column count -- dataset has 48 cols (Z1 has no OutputPower)
    results.append(rule("exp_col_count",
                         len(df.columns) == EXPECTED_EXP_COLS,
                         f"got {len(df.columns)}, expected {EXPECTED_EXP_COLS}"))

    # Machining_Process values
    mp_vals = df["Machining_Process"].dropna().unique().tolist()
    bad_mp  = [v for v in mp_vals if v not in VALID_MACHINING_PROCESS]
    results.append(rule("exp_machining_process_values",
                         len(bad_mp) == 0,
                         f"unknown values: {bad_mp}"))

    # Power columns >= 0 (tiny floating-point negatives near zero are tolerated)
    for col in POWER_COLS:
        if col in df.columns:
            neg_count = (df[col].dropna() < -1e-4).sum()
            results.append(rule(f"exp_{col}_nonneg",
                                 neg_count == 0,
                                 f"{neg_count} values < -1e-4"))

    # No infinite values in numeric columns
    num_cols    = df.select_dtypes(include=[np.number]).columns
    inf_count   = np.isinf(df[num_cols].values).sum()
    results.append(rule("exp_no_infinites",
                         int(inf_count) == 0,
                         f"{inf_count} infinite values"))

    return results


# ---------------------------------------------------------------------------
# Step 2 -- Defect detection
# ---------------------------------------------------------------------------

def add_defect_flags(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Add the 3 defect boolean columns. Returns updated df and count dict."""
    df = df.copy()

    df["defect_feedrate_50"]     = df[DEFECT_COL_FEEDRATE].eq(50)
    df["defect_position_198"]    = df[DEFECT_COL_POSITION].eq(198)
    df["defect_program_nonzero"] = df[DEFECT_COL_PROGRAM].ne(0)

    counts = {
        "defect_feedrate_50":     int(df["defect_feedrate_50"].sum()),
        "defect_position_198":    int(df["defect_position_198"].sum()),
        "defect_program_nonzero": int(df["defect_program_nonzero"].sum()),
    }
    return df, counts


# ---------------------------------------------------------------------------
# Step 3 -- Timestamp index
# ---------------------------------------------------------------------------

def add_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp_ms"] = (df.index * 100).astype("int64")
    return df


# ---------------------------------------------------------------------------
# Step 4 -- Missing value handling
# ---------------------------------------------------------------------------

def _detect_large_gaps(series: pd.Series, max_gap: int = 3) -> pd.Series:
    """
    Return a boolean Series marking rows that are NaN and are part of a
    consecutive NaN run LONGER than max_gap.  These rows should be flagged
    as 'interpolated' even though we still forward-fill them.
    """
    is_null   = series.isna()
    flagged   = pd.Series(False, index=series.index)
    run_start = None
    run_len   = 0

    for i, null in enumerate(is_null):
        if null:
            if run_start is None:
                run_start = i
            run_len += 1
        else:
            if run_start is not None and run_len > max_gap:
                flagged.iloc[run_start:run_start + run_len] = True
            run_start = None
            run_len   = 0

    # Handle trailing run
    if run_start is not None and run_len > max_gap:
        flagged.iloc[run_start:run_start + run_len] = True

    return flagged


def handle_missing_values(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """
    Apply missing-value policy.
    - Position / velocity cols: ffill if gap <= 3; flag interpolated if gap > 3
    - Power cols: flag missing_power, NO imputation
    - Machining_Process: always ffill
    Returns (updated_df, n_interpolated_rows, n_missing_power_rows).
    """
    df = df.copy()

    pos_vel_cols = [c for c in df.columns
                    if "ActualPosition" in c or "ActualVelocity" in c]

    interpolated_flag = pd.Series(False, index=df.index)

    for col in pos_vel_cols:
        large_gap = _detect_large_gaps(df[col], max_gap=3)
        interpolated_flag = interpolated_flag | large_gap
        # Forward-fill regardless (small AND large gaps)
        df[col] = df[col].ffill()

    df["interpolated"] = interpolated_flag

    # Power columns: flag missing, no fill
    missing_power_flag = pd.Series(False, index=df.index)
    for col in POWER_COLS:
        if col in df.columns:
            missing_power_flag = missing_power_flag | df[col].isna()
    df["missing_power"] = missing_power_flag

    # Machining_Process: always ffill
    if "Machining_Process" in df.columns:
        df["Machining_Process"] = df["Machining_Process"].ffill()

    n_interp        = int(interpolated_flag.sum())
    n_missing_power = int(missing_power_flag.sum())
    return df, n_interp, n_missing_power


# ---------------------------------------------------------------------------
# Quality status logic
# ---------------------------------------------------------------------------

def compute_status(validation_rules: list[dict]) -> str:
    """
    FAIL  -- any critical schema rule failed
    WARN  -- non-critical issues (e.g. unexpected Machining_Process values)
    PASS  -- everything clean
    """
    failed = [r for r in validation_rules if not r["passed"]]
    if not failed:
        return "PASS"

    # Rules that are WARN-level (non-fatal schema deviations)
    warn_only_rules = {
        "exp_machining_process_values",    # extra process labels observed
    }
    # Power near-zero negatives are also WARN-level
    warn_only_prefixes = ("exp_X1_OutputPower_nonneg",
                          "exp_Y1_OutputPower_nonneg",
                          "exp_S1_OutputPower_nonneg")

    for r in failed:
        rule_name = r["rule"]
        is_warn = (rule_name in warn_only_rules or
                   any(rule_name.startswith(p) for p in warn_only_prefixes))
        if not is_warn:
            return "FAIL"
    return "WARN"


# ---------------------------------------------------------------------------
# Quality report helpers
# ---------------------------------------------------------------------------

def append_quality_summary(row: dict) -> None:
    SILVER_QUAL_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not QUALITY_SUMMARY.exists()
    with QUALITY_SUMMARY.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_silver() -> None:
    run_id    = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    print()
    log(f"=== Silver Transform -- run_id: {run_id} ===")
    log(f"    Bronze : {BRONZE_DIR}")
    log(f"    Silver : {SILVER_DIR}")
    print()

    # -- Idempotency check --------------------------------------------------
    if silver_is_fresh():
        log("Silver outputs are already newer than Bronze inputs -- skipping.")
        log("Delete data/silver/ to force a re-run.")
        return

    # -- Create output dirs -------------------------------------------------
    SILVER_META_DIR.mkdir(parents=True, exist_ok=True)
    SILVER_EXP_DIR.mkdir(parents=True, exist_ok=True)
    SILVER_QUAL_DIR.mkdir(parents=True, exist_ok=True)

    all_rules:          list[dict] = []
    defect_summary:     dict       = {}
    total_rows          = 0
    total_interp_rows   = 0
    total_mpow_rows     = 0
    exp_files_checked   = 0

    # -----------------------------------------------------------------------
    # Process train.csv
    # -----------------------------------------------------------------------
    log("Step 1a -- Validating train.csv ...")
    train_df = pd.read_csv(BRONZE_META)
    train_rules = validate_train(train_df)
    all_rules.extend(train_rules)

    failed_train = [r for r in train_rules if not r["passed"]]
    if failed_train:
        for r in failed_train:
            log_warn(f"  train.csv rule FAILED: {r['rule']} -- {r['detail']}")
    else:
        log("  train.csv validation: all rules passed.")

    # Add validation_run_id and write to Parquet
    train_silver = train_df.copy()
    train_silver["validation_run_id"] = run_id
    out_train = SILVER_META_DIR / "train_silver.parquet"
    train_silver.to_parquet(out_train, engine="pyarrow", index=False)
    log(f"  Written: {out_train.relative_to(PROJECT_ROOT)}")

    # -----------------------------------------------------------------------
    # Process each experiment
    # -----------------------------------------------------------------------
    exp_files = sorted(BRONZE_EXP_DIR.glob("experiment_*.csv"))
    if not exp_files:
        log_error("No experiment CSV files found in bronze/experiments/")
        sys.exit(1)

    log(f"\nStep 1b-5 -- Processing {len(exp_files)} experiment files ...")

    for src_path in exp_files:
        exp_name = src_path.stem   # e.g. "experiment_01"
        log(f"\n  [{exp_name}]")

        # -- Load --
        df = pd.read_csv(src_path)
        n_rows = len(df)
        total_rows += n_rows

        # -- Step 1: Schema validation --
        exp_rules = validate_experiment(df, exp_name)
        all_rules.extend(exp_rules)

        failed_exp = [r for r in exp_rules if not r["passed"]]
        if failed_exp:
            for r in failed_exp:
                # Machining_Process extras and tiny-negative power: log as WARN
                log_warn(f"    Rule WARN/FAIL: {r['rule']} -- {r['detail']}")
        else:
            log(f"    Schema validation: OK ({n_rows} rows, {len(df.columns)} cols)")

        # -- Step 2: Defect flags --
        df, d_counts = add_defect_flags(df)
        defect_summary[exp_name] = d_counts
        log(f"    Defects -- feedrate_50: {d_counts['defect_feedrate_50']}, "
            f"position_198: {d_counts['defect_position_198']}, "
            f"program_nonzero: {d_counts['defect_program_nonzero']}")

        # -- Step 3: Timestamp --
        df = add_timestamp(df)

        # -- Step 4: Missing values --
        df, n_interp, n_mpow = handle_missing_values(df)
        total_interp_rows += n_interp
        total_mpow_rows   += n_mpow
        if n_interp > 0:
            log_warn(f"    Interpolated (large gap > 3): {n_interp} rows")
        if n_mpow > 0:
            log_warn(f"    Missing power flagged: {n_mpow} rows")

        # -- Add run_id --
        df["validation_run_id"] = run_id

        # -- Write Parquet --
        out_path = SILVER_EXP_DIR / f"{exp_name}_silver.parquet"
        df.to_parquet(out_path, engine="pyarrow", index=False)
        log(f"    Written: {out_path.relative_to(PROJECT_ROOT)}  "
            f"({len(df.columns)} cols)")

        exp_files_checked += 1

    # -----------------------------------------------------------------------
    # Step 5: Quality report
    # -----------------------------------------------------------------------
    log("\nStep 5 -- Generating quality report ...")

    status = compute_status(all_rules)

    failed_rules = [r for r in all_rules if not r["passed"]]
    pct_interp   = round(100.0 * total_interp_rows / max(total_rows, 1), 4)
    pct_mpow     = round(100.0 * total_mpow_rows   / max(total_rows, 1), 4)

    # Aggregate defects by type
    defect_totals = {
        "defect_feedrate_50":     sum(v["defect_feedrate_50"]     for v in defect_summary.values()),
        "defect_position_198":    sum(v["defect_position_198"]    for v in defect_summary.values()),
        "defect_program_nonzero": sum(v["defect_program_nonzero"] for v in defect_summary.values()),
    }

    quality_report = {
        "run_id":              run_id,
        "started_at":          started_at,
        "finished_at":         datetime.now(timezone.utc).isoformat(),
        "status":              status,
        "files_checked": {
            "train":       1,
            "experiments": exp_files_checked,
        },
        "rows": {
            "total":            total_rows,
            "interpolated":     total_interp_rows,
            "pct_interpolated": pct_interp,
            "missing_power":    total_mpow_rows,
            "pct_missing_power": pct_mpow,
        },
        "validation_rules": {
            "total":   len(all_rules),
            "passed":  len(all_rules) - len(failed_rules),
            "failed":  len(failed_rules),
            "details": failed_rules,
        },
        "defect_summary": {
            "by_type":       defect_totals,
            "by_experiment": defect_summary,
        },
    }

    class _JSONEncoder(json.JSONEncoder):
        """Handles numpy scalar types that the standard encoder rejects."""
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            return super().default(obj)

    report_path = SILVER_QUAL_DIR / f"quality_report_{run_id}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, cls=_JSONEncoder)
    log(f"  Quality report: {report_path.relative_to(PROJECT_ROOT)}")

    # Append summary line to CSV
    summary_row = {
        "run_id":             run_id,
        "timestamp":          started_at,
        "status":             status,
        "files_checked":      1 + exp_files_checked,
        "total_rows":         total_rows,
        "rules_passed":       len(all_rules) - len(failed_rules),
        "rules_failed":       len(failed_rules),
        "interpolated_rows":  total_interp_rows,
        "missing_power_rows": total_mpow_rows,
        "defect_feedrate_50":     defect_totals["defect_feedrate_50"],
        "defect_position_198":    defect_totals["defect_position_198"],
        "defect_program_nonzero": defect_totals["defect_program_nonzero"],
    }
    append_quality_summary(summary_row)
    log(f"  Quality summary appended: {QUALITY_SUMMARY.relative_to(PROJECT_ROOT)}")

    # -----------------------------------------------------------------------
    # Final status
    # -----------------------------------------------------------------------
    print()
    if status == "FAIL":
        log_error(f"Pipeline status: FAIL -- {len(failed_rules)} rule(s) failed.")
        log_error("Silver pipeline halted. Review the quality report for details.")
        sys.exit(1)
    elif status == "WARN":
        log_warn(f"Pipeline status: WARN -- {len(failed_rules)} rule(s) raised warnings.")
        log_warn("Silver outputs written. Downstream layers may proceed with caution.")
    else:
        log(f"Pipeline status: PASS -- all {len(all_rules)} rules passed.")

    log(f"\n=== Silver transform complete. run_id: {run_id} ===\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_silver()
