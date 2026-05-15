"""
Gold Layer -- CNC Energy Intelligence Platform
Feature engineering, target construction, split and export.

Usage:
    python src/gold/build.py

Reads:
    data/silver/experiments/experiment_NN_silver.parquet  (x18)
    data/silver/metadata/train_silver.parquet

Produces:
    data/gold/train_gold.parquet            (experiments 01-14)
    data/gold/validation_gold.parquet       (experiments 15-16)
    data/gold/test_gold.parquet             (experiments 17-18)
    data/gold/per_experiment/experiment_NN_gold.parquet
    data/gold/diagnostics/defect_rows.parquet
    data/gold/feature_registry.json
"""

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
PROJECT_ROOT    = Path(__file__).resolve().parents[2]
SILVER_DIR      = PROJECT_ROOT / "data" / "silver"
SILVER_EXP_DIR  = SILVER_DIR / "experiments"
SILVER_META     = SILVER_DIR / "metadata" / "train_silver.parquet"
GOLD_DIR        = PROJECT_ROOT / "data" / "gold"
GOLD_PER_EXP    = GOLD_DIR / "per_experiment"
GOLD_DIAG       = GOLD_DIR / "diagnostics"

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

# Phase encoding: canonical names -> ordinal id
# Note: experiment_01 uses lowercase 'end' -- normalised to 'End' on load.
PHASE_MAP = {
    "Starting":      0,
    "Prep":          1,
    "Layer 1 Up":    2,
    "Layer 1 Down":  3,
    "Layer 2 Up":    4,
    "Layer 2 Down":  5,
    "Layer 3 Up":    6,
    "Layer 3 Down":  7,
    "End":           8,
    "Repositioning": 9,
}
CUTTING_PHASE_IDS = {2, 3, 4, 5, 6, 7}  # Layer X Up / Down

# Columns targeted by lag and rolling features
LAG_ROLL_COLS = [
    "X1_OutputPower",
    "Y1_OutputPower",
    "S1_OutputPower",
    "M1_CURRENT_FEEDRATE",
]

# Lag offsets (in rows; 1 row = 100 ms)
LAG_OFFSETS = [1, 5, 10, 30, 60]

# Rolling windows and their statistics
ROLLING_SPECS = [
    (10, ["mean", "std", "min", "max"]),
    (30, ["mean", "std"]),
    (60, ["mean"]),
]

# Split boundaries (experiment number, 1-indexed)
TRAIN_EXP_RANGE      = range(1, 15)   # 01-14
VALIDATION_EXP_RANGE = range(15, 17)  # 15-16
TEST_EXP_RANGE       = range(17, 19)  # 17-18

# ---------------------------------------------------------------------------
# Logging helpers (ASCII-only -- Windows cp1252 safe)
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

def gold_is_fresh() -> bool:
    """Return True if all expected Gold outputs exist and are newer than Silver inputs."""
    silver_files = list(SILVER_EXP_DIR.glob("*.parquet")) + [SILVER_META]
    if not silver_files:
        return False
    latest_silver = max(f.stat().st_mtime for f in silver_files if f.exists())

    required_gold = [
        GOLD_DIR / "train_gold.parquet",
        GOLD_DIR / "validation_gold.parquet",
        GOLD_DIR / "test_gold.parquet",
        GOLD_DIR / "feature_registry.json",
        GOLD_DIAG / "defect_rows.parquet",
    ]
    if not all(p.exists() for p in required_gold):
        return False

    earliest_gold = min(p.stat().st_mtime for p in required_gold)
    return earliest_gold > latest_silver


# ---------------------------------------------------------------------------
# Step 1 -- Remove defects
# ---------------------------------------------------------------------------

def remove_defects(df: pd.DataFrame, exp_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Drop rows with defect_feedrate_50=True or defect_position_198=True.
    Also drop defect_program_nonzero column (no signal).
    Returns (clean_df, defect_df).
    """
    mask_defect = df["defect_feedrate_50"] | df["defect_position_198"]
    defect_df   = df[mask_defect].copy()
    clean_df    = df[~mask_defect].copy()

    # Drop the no-signal column from the clean frame
    if "defect_program_nonzero" in clean_df.columns:
        clean_df = clean_df.drop(columns=["defect_program_nonzero"])

    n_before  = len(df)
    n_dropped = len(defect_df)
    n_after   = len(clean_df)
    pct       = 100.0 * n_dropped / n_before if n_before > 0 else 0.0

    log(f"    Defect filter: {n_before} -> {n_after} rows "
        f"({n_dropped} dropped, {pct:.1f}%)")

    return clean_df, defect_df


# ---------------------------------------------------------------------------
# Step 2 -- Metadata join
# ---------------------------------------------------------------------------

def load_metadata(run_id: str) -> pd.DataFrame:
    """Load and encode metadata from train_silver.parquet."""
    meta = pd.read_parquet(SILVER_META)

    # Encode tool_condition: unworn=0, worn=1
    meta["tool_condition_enc"] = meta["tool_condition"].map({"unworn": 0, "worn": 1})

    # Encode machining_finalized: no=0, yes=1
    meta["machining_finalized_enc"] = meta["machining_finalized"].map({"no": 0, "yes": 1})

    # Encode passed_visual_inspection: no=0, yes=1, NaN=-1
    def encode_inspection(val):
        if pd.isna(val):
            return -1
        return 1 if val == "yes" else 0

    meta["passed_visual_inspection_enc"] = meta["passed_visual_inspection"].apply(encode_inspection)

    return meta


def join_metadata(df: pd.DataFrame, exp_num: int, meta: pd.DataFrame) -> pd.DataFrame:
    """Broadcast metadata row for experiment exp_num onto all rows of df."""
    row = meta[meta["No"] == exp_num].iloc[0]

    df = df.copy()
    df["feedrate"]                      = row["feedrate"]
    df["clamp_pressure"]                = row["clamp_pressure"]
    df["tool_condition_enc"]            = int(row["tool_condition_enc"])
    df["machining_finalized_enc"]       = int(row["machining_finalized_enc"])
    df["passed_visual_inspection_enc"]  = int(row["passed_visual_inspection_enc"])

    return df


# ---------------------------------------------------------------------------
# Step 3 -- Phase encoding
# ---------------------------------------------------------------------------

def encode_phases(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add phase_id, is_cutting_phase, phase_row_index, phase_duration_rows.
    All computed per experiment (called on a single experiment dataframe).
    'end' (lowercase) is normalised to 'End' to handle experiment_01.
    """
    df = df.copy()

    # Normalise capitalisation inconsistency in experiment_01
    df["Machining_Process"] = df["Machining_Process"].replace({"end": "End"})

    # Map phase label to ordinal id
    df["phase_id"] = df["Machining_Process"].map(PHASE_MAP)

    # Warn if any label is unmapped (NaN in phase_id)
    unmapped = df["Machining_Process"][df["phase_id"].isna()].unique().tolist()
    if unmapped:
        log_warn(f"    Unknown Machining_Process labels (will be NaN): {unmapped}")

    df["phase_id"] = df["phase_id"].astype("Int64")  # nullable int

    # is_cutting_phase
    df["is_cutting_phase"] = df["phase_id"].isin(CUTTING_PHASE_IDS)

    # Detect phase transitions: assign a unique group id per contiguous block
    # This handles the case where the same phase label appears non-contiguously
    # (e.g. Repositioning appears multiple times)
    phase_change = (df["phase_id"] != df["phase_id"].shift()).cumsum()
    df["_phase_block"] = phase_change

    # phase_row_index: position within the current contiguous block (0-based)
    df["phase_row_index"] = df.groupby("_phase_block").cumcount()

    # phase_duration_rows: total rows in this contiguous phase block
    df["phase_duration_rows"] = df.groupby("_phase_block")["_phase_block"].transform("count")

    df = df.drop(columns=["_phase_block"])

    return df


# ---------------------------------------------------------------------------
# Step 4 -- Lag features (within experiment only)
# ---------------------------------------------------------------------------

def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add lag features for LAG_ROLL_COLS x LAG_OFFSETS.
    Called on a single experiment dataframe -- no cross-experiment leakage.
    """
    df = df.copy()
    for col in LAG_ROLL_COLS:
        if col not in df.columns:
            log_warn(f"    Lag: column '{col}' not found, skipping.")
            continue
        for n in LAG_OFFSETS:
            df[f"{col}_lag_{n}"] = df[col].shift(n)
    return df


# ---------------------------------------------------------------------------
# Step 5 -- Rolling window features (within experiment only)
# ---------------------------------------------------------------------------

def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add rolling statistics for LAG_ROLL_COLS x ROLLING_SPECS.
    Called on a single experiment dataframe -- no cross-experiment leakage.
    """
    df = df.copy()
    for col in LAG_ROLL_COLS:
        if col not in df.columns:
            log_warn(f"    Rolling: column '{col}' not found, skipping.")
            continue
        for window, stats in ROLLING_SPECS:
            roller = df[col].rolling(window=window, min_periods=1)
            for stat in stats:
                feat_name = f"{col}_roll{window}_{stat}"
                if stat == "mean":
                    df[feat_name] = roller.mean()
                elif stat == "std":
                    df[feat_name] = roller.std()
                elif stat == "min":
                    df[feat_name] = roller.min()
                elif stat == "max":
                    df[feat_name] = roller.max()
    return df


# ---------------------------------------------------------------------------
# Step 6 -- Phase aggregations (broadcast via transform)
# ---------------------------------------------------------------------------

def add_phase_aggregations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add phase-level power aggregates, broadcast to all rows of each phase block.
    Uses (_phase_block_id) to aggregate over contiguous phase segments.
    NOTE: groupby(['experiment_id', 'phase_id']) as spec requires -- here the
    dataframe is already per-experiment so we groupby 'phase_id' alone, but
    we use the contiguous-block approach (same as phase encoding) to avoid
    mixing non-adjacent repetitions of the same phase_id.
    """
    df = df.copy()

    # Reconstruct contiguous block id for accurate phase-level aggregation
    phase_change = (df["phase_id"] != df["phase_id"].shift()).cumsum()
    df["_phase_block"] = phase_change

    # Intermediate: total power per row
    df["_total_power_row"] = (
        df["X1_OutputPower"] + df["Y1_OutputPower"] + df["S1_OutputPower"]
    )

    # Broadcast aggregations
    df["phase_power_total"] = df.groupby("_phase_block")["_total_power_row"].transform("sum")
    df["phase_power_mean"]  = df.groupby("_phase_block")["_total_power_row"].transform("mean")
    df["phase_power_peak"]  = df.groupby("_phase_block")["_total_power_row"].transform("max")

    # phase_energy_kwh = phase_power_mean x phase_duration_rows x 0.1 / 3600
    df["phase_energy_kwh"] = (
        df["phase_power_mean"] * df["phase_duration_rows"] * 0.1 / 3600.0
    )

    df = df.drop(columns=["_phase_block", "_total_power_row"])
    return df


# ---------------------------------------------------------------------------
# Step 7 -- Cross features
# ---------------------------------------------------------------------------

def add_cross_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["total_output_power"]    = (
        df["X1_OutputPower"] + df["Y1_OutputPower"] + df["S1_OutputPower"]
    )
    df["power_spindle_ratio"]   = df["S1_OutputPower"] / (df["total_output_power"] + 1e-9)
    df["xy_power_ratio"]        = df["X1_OutputPower"] / (df["Y1_OutputPower"] + 1e-9)
    df["velocity_magnitude_xy"] = np.sqrt(
        df["X1_ActualVelocity"] ** 2 + df["Y1_ActualVelocity"] ** 2
    )
    return df


# ---------------------------------------------------------------------------
# Step 8 -- Target construction (within experiment only)
# ---------------------------------------------------------------------------

def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add forward-looking target columns, then drop tail rows with NaN targets.
    Shift(-N) looks N rows ahead -- applied per experiment only.
    """
    df = df.copy()
    df["target_power_next_1s"] = df["total_output_power"].shift(-10)   # 10 rows x 100ms = 1s
    df["target_power_next_3s"] = df["total_output_power"].shift(-30)   # 30 rows x 100ms = 3s

    # Drop rows where either target is NaN (tail of experiment)
    n_before = len(df)
    df = df.dropna(subset=["target_power_next_1s", "target_power_next_3s"])
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        log(f"    Targets: dropped {n_dropped} tail rows (NaN targets)")

    return df


# ---------------------------------------------------------------------------
# Feature registry builder
# ---------------------------------------------------------------------------

def build_feature_registry(df: pd.DataFrame, run_id: str) -> list[dict]:
    """
    Construct feature registry entries for every column in df.
    Returns list of entry dicts matching the spec schema.
    """
    registry = []

    # Categorise columns by their origin
    source_cols = [
        "X1_ActualPosition", "X1_ActualVelocity", "X1_ActualAcceleration",
        "X1_CommandPosition", "X1_CommandVelocity", "X1_CommandAcceleration",
        "X1_CurrentFeedback", "X1_DCBusVoltage", "X1_OutputCurrent",
        "X1_OutputVoltage", "X1_OutputPower",
        "Y1_ActualPosition", "Y1_ActualVelocity", "Y1_ActualAcceleration",
        "Y1_CommandPosition", "Y1_CommandVelocity", "Y1_CommandAcceleration",
        "Y1_CurrentFeedback", "Y1_DCBusVoltage", "Y1_OutputCurrent",
        "Y1_OutputVoltage", "Y1_OutputPower",
        "Z1_ActualPosition", "Z1_ActualVelocity", "Z1_ActualAcceleration",
        "Z1_CommandPosition", "Z1_CommandVelocity", "Z1_CommandAcceleration",
        "Z1_CurrentFeedback", "Z1_DCBusVoltage", "Z1_OutputCurrent",
        "Z1_OutputVoltage",
        "S1_ActualPosition", "S1_ActualVelocity", "S1_ActualAcceleration",
        "S1_CommandPosition", "S1_CommandVelocity", "S1_CommandAcceleration",
        "S1_CurrentFeedback", "S1_DCBusVoltage", "S1_OutputCurrent",
        "S1_OutputVoltage", "S1_OutputPower", "S1_SystemInertia",
        "M1_CURRENT_PROGRAM_NUMBER", "M1_sequence_number", "M1_CURRENT_FEEDRATE",
        "Machining_Process",
    ]
    silver_cols = [
        "timestamp_ms", "defect_feedrate_50", "defect_position_198",
        "missing_power", "interpolated", "validation_run_id",
    ]
    print("")
    metadata_cols = [
        "feedrate", "clamp_pressure",
        "tool_condition_enc", "machining_finalized_enc",
        "passed_visual_inspection_enc",
    ]
    phase_cols = [
        "phase_id", "is_cutting_phase", "phase_row_index", "phase_duration_rows",
    ]
    phase_agg_cols = [
        "phase_power_total", "phase_power_mean", "phase_power_peak", "phase_energy_kwh",
    ]
    cross_cols = [
        "total_output_power", "power_spindle_ratio",
        "xy_power_ratio", "velocity_magnitude_xy",
    ]
    target_cols = ["target_power_next_1s", "target_power_next_3s"]
    infra_cols  = ["experiment_id", "gold_run_id"]

    # Build lookup sets for quick membership test
    lag_roll_set = set()
    for col in LAG_ROLL_COLS:
        for n in LAG_OFFSETS:
            lag_roll_set.add(f"{col}_lag_{n}")
        for window, stats in ROLLING_SPECS:
            for stat in stats:
                lag_roll_set.add(f"{col}_roll{window}_{stat}")

    def dtype_str(col: str) -> str:
        if col in df.columns:
            return str(df[col].dtype)
        return "float64"

    def make_entry(
        name: str,
        source: str,
        transformation: str,
        is_target: bool = False,
        notes: str = "",
    ) -> dict:
        return {
            "feature_name":    name,
            "dtype":           dtype_str(name),
            "source_column":   source,
            "transformation":  transformation,
            "layer":           "gold",
            "is_target":       is_target,
            "notes":           notes,
        }

    # Infrastructure / traceability columns
    for col in infra_cols:
        if col in df.columns:
            registry.append(make_entry(col, col, "traceability ID", notes="Pipeline traceability"))

    # Source sensor columns (pass-through from Silver)
    for col in source_cols:
        if col in df.columns:
            registry.append(make_entry(col, col, "pass-through from Silver", notes="Raw sensor signal"))

    # Silver flag columns retained in Gold
    for col in silver_cols:
        if col in df.columns:
            registry.append(make_entry(col, col, "pass-through from Silver", notes="Quality flag from Silver layer"))

    # Metadata broadcast columns
    meta_desc = {
        "feedrate":                     ("feedrate", "broadcast from train metadata"),
        "clamp_pressure":               ("clamp_pressure", "broadcast from train metadata"),
        "tool_condition_enc":           ("tool_condition", "encoded: unworn=0, worn=1"),
        "machining_finalized_enc":      ("machining_finalized", "encoded: no=0, yes=1"),
        "passed_visual_inspection_enc": ("passed_visual_inspection", "encoded: no=0, yes=1, missing=-1"),
    }
    for col, (src, trans) in meta_desc.items():
        if col in df.columns:
            registry.append(make_entry(col, src, trans, notes="Broadcast to every row of the experiment"))

    # Phase encoding columns
    phase_desc = {
        "phase_id":           ("Machining_Process", "ordinal encoding: Starting=0 .. Repositioning=9"),
        "is_cutting_phase":   ("Machining_Process", "True for Layer X Up/Down (phase_id 2-7)"),
        "phase_row_index":    ("Machining_Process", "row position within current phase block (0-based)"),
        "phase_duration_rows":("Machining_Process", "total rows in current phase block"),
    }
    for col, (src, trans) in phase_desc.items():
        if col in df.columns:
            registry.append(make_entry(col, src, trans, notes="Computed per experiment only"))

    # Lag features
    lag_ms_map = {1: 100, 5: 500, 10: 1000, 30: 3000, 60: 6000}
    for col in LAG_ROLL_COLS:
        for n in LAG_OFFSETS:
            feat = f"{col}_lag_{n}"
            if feat in df.columns:
                registry.append(make_entry(
                    feat, col,
                    f"lag_{n} ({lag_ms_map[n]}ms lookback)",
                    notes="Applied within experiment boundaries only",
                ))

    # Rolling features
    roll_ms_map = {10: "1s", 30: "3s", 60: "6s"}
    for col in LAG_ROLL_COLS:
        for window, stats in ROLLING_SPECS:
            for stat in stats:
                feat = f"{col}_roll{window}_{stat}"
                if feat in df.columns:
                    registry.append(make_entry(
                        feat, col,
                        f"rolling {stat} over {window} rows ({roll_ms_map[window]} window)",
                        notes="Applied within experiment boundaries only",
                    ))

    # Phase aggregation columns
    phase_agg_desc = {
        "phase_power_total": ("X1/Y1/S1_OutputPower", "sum of total power over phase block"),
        "phase_power_mean":  ("X1/Y1/S1_OutputPower", "mean of total power over phase block"),
        "phase_power_peak":  ("X1/Y1/S1_OutputPower", "max of total power over phase block"),
        "phase_energy_kwh":  ("X1/Y1/S1_OutputPower", "phase_power_mean x phase_duration_rows x 0.1 / 3600"),
    }
    for col, (src, trans) in phase_agg_desc.items():
        if col in df.columns:
            registry.append(make_entry(col, src, trans, notes="Broadcast to all rows of phase block"))

    # Cross features
    cross_desc = {
        "total_output_power":    ("X1/Y1/S1_OutputPower", "X1 + Y1 + S1 OutputPower"),
        "power_spindle_ratio":   ("S1_OutputPower", "S1 / (total_output_power + 1e-9)"),
        "xy_power_ratio":        ("X1_OutputPower", "X1 / (Y1 + 1e-9)"),
        "velocity_magnitude_xy": ("X1/Y1_ActualVelocity", "sqrt(X1_vel^2 + Y1_vel^2)"),
    }
    for col, (src, trans) in cross_desc.items():
        if col in df.columns:
            registry.append(make_entry(col, src, trans))

    # Targets
    target_desc = {
        "target_power_next_1s": ("total_output_power", "shift(-10 rows) = 1s ahead"),
        "target_power_next_3s": ("total_output_power", "shift(-30 rows) = 3s ahead"),
    }
    for col, (src, trans) in target_desc.items():
        if col in df.columns:
            registry.append(make_entry(
                col, src, trans,
                is_target=True,
                notes="Applied within experiment boundaries only; NaN tail rows dropped",
            ))

    return registry


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_gold() -> None:
    run_id     = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    print()
    log(f"=== Gold Build -- run_id: {run_id} ===")
    log(f"    Silver : {SILVER_DIR}")
    log(f"    Gold   : {GOLD_DIR}")
    print()

    # -- Idempotency check --------------------------------------------------
    if gold_is_fresh():
        log("Gold outputs are already newer than Silver inputs -- skipping.")
        log("Delete data/gold/ to force a re-run.")
        return

    # -- Create output dirs -------------------------------------------------
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    GOLD_PER_EXP.mkdir(parents=True, exist_ok=True)
    GOLD_DIAG.mkdir(parents=True, exist_ok=True)

    # -- Load metadata once -------------------------------------------------
    log("Loading metadata from train_silver.parquet ...")
    meta = load_metadata(run_id)
    log(f"  Metadata: {len(meta)} experiment records loaded")

    # -- Discover Silver experiment files ------------------------------------
    silver_files = sorted(SILVER_EXP_DIR.glob("experiment_*_silver.parquet"))
    if not silver_files:
        log_error("No Silver experiment files found.")
        sys.exit(1)
    log(f"  Found {len(silver_files)} Silver experiment files")

    # -- Processing loop ----------------------------------------------------
    all_defect_rows: list[pd.DataFrame] = []
    processed_frames: dict[int, pd.DataFrame] = {}  # exp_num -> gold df

    for silver_path in silver_files:
        # Extract experiment number from filename e.g. "experiment_03_silver" -> 3
        stem    = silver_path.stem                      # "experiment_03_silver"
        parts   = stem.split("_")                       # ["experiment", "03", "silver"]
        exp_num = int(parts[1])                         # 3
        exp_id  = f"experiment_{parts[1]}"              # "experiment_03"

        print()
        log(f"  [{exp_id}]  (No {exp_num})")

        # -- Load -----------------------------------------------------------
        df = pd.read_parquet(silver_path)
        log(f"    Loaded: {len(df)} rows, {len(df.columns)} cols")

        # Add experiment identifiers
        df["experiment_id"] = exp_id
        df["gold_run_id"]   = run_id

        # ----------------------------------------------------------------
        # Step 1 -- Remove defects
        # ----------------------------------------------------------------
        df, defect_df = remove_defects(df, exp_id)
        defect_df["experiment_id"] = exp_id
        all_defect_rows.append(defect_df)

        if len(df) == 0:
            log_warn(f"    All rows removed for {exp_id} -- skipping this experiment.")
            continue

        # ----------------------------------------------------------------
        # Step 2 -- Metadata join
        # ----------------------------------------------------------------
        df = join_metadata(df, exp_num, meta)
        log(f"    Metadata joined: tool={meta.loc[meta['No']==exp_num,'tool_condition'].iloc[0]}, "
            f"feedrate={meta.loc[meta['No']==exp_num,'feedrate'].iloc[0]}, "
            f"clamp={meta.loc[meta['No']==exp_num,'clamp_pressure'].iloc[0]}")

        # ----------------------------------------------------------------
        # Step 3 -- Phase encoding (per experiment)
        # ----------------------------------------------------------------
        df = encode_phases(df)
        phase_counts = df["phase_id"].value_counts().sort_index().to_dict()
        log(f"    Phase encoding done. Phase distribution: {phase_counts}")

        # ----------------------------------------------------------------
        # Step 4 -- Lag features (per experiment)
        # ----------------------------------------------------------------
        df = add_lag_features(df)
        n_lag_feats = len(LAG_ROLL_COLS) * len(LAG_OFFSETS)
        log(f"    Lag features added: {n_lag_feats} columns")

        # ----------------------------------------------------------------
        # Step 5 -- Rolling window features (per experiment)
        # ----------------------------------------------------------------
        df = add_rolling_features(df)
        n_roll_feats = sum(len(stats) for _, stats in ROLLING_SPECS) * len(LAG_ROLL_COLS)
        log(f"    Rolling features added: {n_roll_feats} columns")

        # ----------------------------------------------------------------
        # Step 6 -- Phase aggregations (per experiment)
        # ----------------------------------------------------------------
        df = add_phase_aggregations(df)
        log(f"    Phase aggregations added: phase_power_total/mean/peak/energy_kwh")

        # ----------------------------------------------------------------
        # Step 7 -- Cross features
        # ----------------------------------------------------------------
        df = add_cross_features(df)
        log(f"    Cross features added: total_output_power, power_spindle_ratio, "
            f"xy_power_ratio, velocity_magnitude_xy")

        # ----------------------------------------------------------------
        # Step 8 -- Target construction (per experiment)
        # ----------------------------------------------------------------
        df = add_targets(df)

        # ----------------------------------------------------------------
        # Export per-experiment file
        # ----------------------------------------------------------------
        per_exp_path = GOLD_PER_EXP / f"{exp_id}_gold.parquet"
        df.to_parquet(per_exp_path, engine="pyarrow", index=False)
        log(f"    Written: {per_exp_path.relative_to(PROJECT_ROOT)}  "
            f"({len(df)} rows, {len(df.columns)} cols)")

        processed_frames[exp_num] = df

    # -- Save defect rows ---------------------------------------------------
    print()
    log("Saving defect rows ...")
    if all_defect_rows:
        defect_combined = pd.concat(all_defect_rows, ignore_index=True)
        defect_path = GOLD_DIAG / "defect_rows.parquet"
        defect_combined.to_parquet(defect_path, engine="pyarrow", index=False)
        log(f"  defect_rows.parquet: {len(defect_combined)} rows saved "
            f"({defect_path.relative_to(PROJECT_ROOT)})")
    else:
        log_warn("  No defect rows found across all experiments.")

    # -- Step 9 -- Split and export -----------------------------------------
    log("Splitting into train / validation / test ...")

    def collect_split(exp_range: range) -> pd.DataFrame:
        frames = [processed_frames[n] for n in exp_range if n in processed_frames]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    train_df = collect_split(TRAIN_EXP_RANGE)
    val_df   = collect_split(VALIDATION_EXP_RANGE)
    test_df  = collect_split(TEST_EXP_RANGE)

    splits = [
        (train_df,  GOLD_DIR / "train_gold.parquet",      "Train      (exp 01-14)"),
        (val_df,    GOLD_DIR / "validation_gold.parquet",  "Validation (exp 15-16)"),
        (test_df,   GOLD_DIR / "test_gold.parquet",        "Test       (exp 17-18)"),
    ]
    for split_df, split_path, label in splits:
        if len(split_df) == 0:
            log_warn(f"  {label}: empty -- no file written.")
            continue
        split_df.to_parquet(split_path, engine="pyarrow", index=False)
        log(f"  {label}: {len(split_df):>6} rows, {len(split_df.columns)} cols "
            f"-> {split_path.name}")

    # -- Feature registry ---------------------------------------------------
    log("Building feature registry ...")
    ref_df = train_df if len(train_df) > 0 else val_df
    if len(ref_df) == 0 and processed_frames:
        ref_df = next(iter(processed_frames.values()))

    registry = build_feature_registry(ref_df, run_id)
    registry_path = GOLD_DIR / "feature_registry.json"
    with registry_path.open("w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)

    n_features = sum(1 for e in registry if not e["is_target"])
    n_targets  = sum(1 for e in registry if e["is_target"])
    log(f"  Feature registry: {len(registry)} entries "
        f"({n_features} features + {n_targets} targets) "
        f"-> {registry_path.name}")

    # -- Summary ------------------------------------------------------------
    total_rows = sum(len(f) for f in processed_frames.values())
    n_cols     = len(ref_df.columns) if len(ref_df) > 0 else 0

    print()
    log(f"=== Gold Build complete. run_id: {run_id} ===")
    log(f"    Experiments processed : {len(processed_frames)}")
    log(f"    Total clean rows      : {total_rows}")
    log(f"    Feature columns       : {n_cols}")
    log(f"    Features in registry  : {n_features} features + {n_targets} targets")
    log(f"    Train rows            : {len(train_df)}")
    log(f"    Validation rows       : {len(val_df)}")
    log(f"    Test rows             : {len(test_df)}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_gold()
