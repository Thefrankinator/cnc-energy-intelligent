# Silver Quality Report — Full Analysis
**run_id**: `589176dc-8ac3-49dd-98f1-0403fc2c3afa`
**Date**: 2026-05-15 | **Duration**: 1.7s | **Status**: WARN

---

## Summary

| Metric | Value |
|---|---|
| Total rows | 25,286 |
| Files checked | 19 (1 metadata + 18 experiments) |
| Validation rules | 135 total — 78 passed, 57 WARN |
| Missing power values | 0 |
| Interpolated rows | 0 |

---

## The 135 Rules — Full Breakdown

### Structure: 9 + (7 × 18) = 135

#### 9 rules on `train.csv` (run once) — all passed

| Rule | What it checks | Result |
|---|---|---|
| `train_row_count` | Exactly 18 rows | PASS |
| `train_col_count` | Exactly 7 columns | PASS |
| `train_no_range_nodups` | Column `No` = integers 1..18, no duplicates, no gaps | PASS |
| `train_tool_condition` | Values ∈ {unworn, worn} | PASS |
| `train_feedrate` | Values ∈ {3, 6, 12, 15, 20} | PASS |
| `train_clamp_pressure` | Values ∈ {2.5, 3.0, 4.0} | PASS |
| `train_machining_finalized` | Values ∈ {yes, no} | PASS |
| `train_passed_visual_inspection` | Values ∈ {yes, no, empty} | PASS |
| `train_no_fully_null_rows` | No row is entirely null | PASS |

#### 7 rules × 18 experiments = 126 rules

Each experiment file gets the same 7 checks:

| Rule | What it checks |
|---|---|
| `exp_not_empty` | File has at least 1 row |
| `exp_col_count` | Exactly 48 columns *(adjusted from 53 — Z1_OutputPower absent in dataset)* |
| `exp_machining_process_values` | Phase labels are in the valid set |
| `exp_X1_OutputPower_nonneg` | X-axis power >= -1e-4 |
| `exp_Y1_OutputPower_nonneg` | Y-axis power >= -1e-4 |
| `exp_S1_OutputPower_nonneg` | Spindle power >= -1e-4 |
| `exp_no_infinites` | No +Inf / -Inf in any numeric column |

Most experiments pass 5-6 out of 7. The 2 that repeatedly fail are `exp_machining_process_values` (label `End` not in original spec) and one of the power negativity checks (float noise ~1e-6).

---

## Validation Warnings (57)

Two root causes account for all 57 warnings:

### 1. `exp_machining_process_values` — 17/18 experiments
Label `End` appears in the dataset but was not in the original spec. `Repositioning` also observed.
Both added to the valid set and classified as WARN (not FAIL).

### 2. Power negativity (float noise) — X1, Y1, S1
Sensor readings slightly below zero (e.g. `-1.42e-06`) due to floating-point instrument noise at idle.
Values between `-1e-4` and `0` are tolerated as WARN — not flagged as defects.

| Rule | Experiments affected |
|---|---|
| `exp_S1_OutputPower_nonneg` | 17/18 |
| `exp_machining_process_values` | 17/18 |
| `exp_X1_OutputPower_nonneg` | 12/18 |
| `exp_Y1_OutputPower_nonneg` | 7/18 |

### Detail per experiment

| File | Rule | Detail |
|---|---|---|
| experiment_01 | exp_X1_OutputPower_nonneg | 2 values < -1e-4 |
| experiment_02 | exp_machining_process_values | unknown values: ['End'] |
| experiment_02 | exp_X1_OutputPower_nonneg | 4 values < -1e-4 |
| experiment_02 | exp_Y1_OutputPower_nonneg | 13 values < -1e-4 |
| experiment_02 | exp_S1_OutputPower_nonneg | 11 values < -1e-4 |
| experiment_03 | exp_machining_process_values | unknown values: ['End'] |
| experiment_03 | exp_X1_OutputPower_nonneg | 4 values < -1e-4 |
| experiment_03 | exp_Y1_OutputPower_nonneg | 1 values < -1e-4 |
| experiment_03 | exp_S1_OutputPower_nonneg | 8 values < -1e-4 |
| experiment_04 | exp_machining_process_values | unknown values: ['End'] |
| experiment_04 | exp_Y1_OutputPower_nonneg | 1 values < -1e-4 |
| experiment_04 | exp_S1_OutputPower_nonneg | 8 values < -1e-4 |
| experiment_05 | exp_machining_process_values | unknown values: ['End'] |
| experiment_05 | exp_X1_OutputPower_nonneg | 4 values < -1e-4 |
| experiment_05 | exp_Y1_OutputPower_nonneg | 1 values < -1e-4 |
| experiment_05 | exp_S1_OutputPower_nonneg | 10 values < -1e-4 |
| experiment_06 | exp_machining_process_values | unknown values: ['End'] |
| experiment_06 | exp_S1_OutputPower_nonneg | 10 values < -1e-4 |
| experiment_07 | exp_machining_process_values | unknown values: ['End'] |
| experiment_07 | exp_X1_OutputPower_nonneg | 7 values < -1e-4 |
| experiment_07 | exp_Y1_OutputPower_nonneg | 3 values < -1e-4 |
| experiment_07 | exp_S1_OutputPower_nonneg | 10 values < -1e-4 |
| experiment_08 | exp_machining_process_values | unknown values: ['End'] |
| experiment_08 | exp_X1_OutputPower_nonneg | 6 values < -1e-4 |
| experiment_08 | exp_Y1_OutputPower_nonneg | 13 values < -1e-4 |
| experiment_08 | exp_S1_OutputPower_nonneg | 7 values < -1e-4 |
| experiment_09 | exp_machining_process_values | unknown values: ['End'] |
| experiment_09 | exp_X1_OutputPower_nonneg | 5 values < -1e-4 |
| experiment_09 | exp_Y1_OutputPower_nonneg | 5 values < -1e-4 |
| experiment_09 | exp_S1_OutputPower_nonneg | 7 values < -1e-4 |
| experiment_10 | exp_machining_process_values | unknown values: ['End'] |
| experiment_10 | exp_X1_OutputPower_nonneg | 5 values < -1e-4 |
| experiment_10 | exp_Y1_OutputPower_nonneg | 7 values < -1e-4 |
| experiment_10 | exp_S1_OutputPower_nonneg | 6 values < -1e-4 |
| experiment_11 | exp_machining_process_values | unknown values: ['End'] |
| experiment_11 | exp_X1_OutputPower_nonneg | 1 values < -1e-4 |
| experiment_11 | exp_S1_OutputPower_nonneg | 11 values < -1e-4 |
| experiment_12 | exp_machining_process_values | unknown values: ['End'] |
| experiment_12 | exp_X1_OutputPower_nonneg | 2 values < -1e-4 |
| experiment_12 | exp_S1_OutputPower_nonneg | 12 values < -1e-4 |
| experiment_13 | exp_machining_process_values | unknown values: ['End'] |
| experiment_13 | exp_X1_OutputPower_nonneg | 1 values < -1e-4 |
| experiment_13 | exp_S1_OutputPower_nonneg | 11 values < -1e-4 |
| experiment_14 | exp_machining_process_values | unknown values: ['End'] |
| experiment_14 | exp_S1_OutputPower_nonneg | 8 values < -1e-4 |
| experiment_15 | exp_machining_process_values | unknown values: ['End'] |
| experiment_15 | exp_X1_OutputPower_nonneg | 2 values < -1e-4 |
| experiment_15 | exp_S1_OutputPower_nonneg | 10 values < -1e-4 |
| experiment_16 | exp_machining_process_values | unknown values: ['End'] |
| experiment_16 | exp_X1_OutputPower_nonneg | 4 values < -1e-4 |
| experiment_16 | exp_Y1_OutputPower_nonneg | 3 values < -1e-4 |
| experiment_16 | exp_S1_OutputPower_nonneg | 12 values < -1e-4 |
| experiment_17 | exp_machining_process_values | unknown values: ['End'] |
| experiment_17 | exp_S1_OutputPower_nonneg | 7 values < -1e-4 |
| experiment_18 | exp_machining_process_values | unknown values: ['End'] |
| experiment_18 | exp_X1_OutputPower_nonneg | 1 values < -1e-4 |
| experiment_18 | exp_S1_OutputPower_nonneg | 7 values < -1e-4 |

---

## Defect Summary

### By type

| Defect flag | Rows | % of total | Notes |
|---|---|---|---|
| `defect_feedrate_50` | 6,253 | 24.7% | Real defect — filter in Gold |
| `defect_position_198` | 4,360 | 17.2% | Real defect — filter in Gold |
| `defect_program_nonzero` | 24,581 | 97.2% | Program 1 always active — not discriminative, consider dropping in Gold |

### By experiment

| Experiment | feedrate_50 | position_198 | program_nonzero |
|---|---|---|---|
| experiment_01 | 64 | 2 | 1,055 |
| experiment_02 | 1,292 | 1,206 | 963 |
| experiment_03 | 210 | 318 | 1,521 |
| experiment_04 | 244 | 317 | 532 |
| experiment_05 | 153 | 347 | 462 |
| experiment_06 | 305 | 161 | 1,296 |
| experiment_07 | 179 | 215 | 565 |
| experiment_08 | 144 | 138 | 605 |
| experiment_09 | 322 | 176 | 740 |
| experiment_10 | 789 | 285 | 1,301 |
| experiment_11 | 349 | 219 | 2,314 |
| experiment_12 | 315 | 83 | 2,276 |
| experiment_13 | 272 | 127 | 2,233 |
| experiment_14 | 366 | 100 | 2,332 |
| experiment_15 | 385 | 140 | 1,381 |
| experiment_16 | 496 | 425 | 602 |
| experiment_17 | 182 | 0 | 2,150 |
| experiment_18 | 186 | 101 | 2,253 |

**Notable:**
- Experiment 02 — most defective (highest feedrate_50 + position_198)
- Experiment 17 — zero position_198 defects, cleanest on that metric
- Experiments 11–14, 17–18 — near-100% program_nonzero (long experiments, program always running)

---

## Decisions for Gold Layer

- `defect_feedrate_50` and `defect_position_198` — filter these rows out of training data
- `defect_program_nonzero` — consider dropping the column entirely (97.2% True = no signal)
- Float noise in power columns — no action needed, values treated as ~0 by the model
- `End` / `Repositioning` phases — include as valid phases in Gold phase encoding
