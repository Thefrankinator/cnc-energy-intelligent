	# Gold Layer Recap -- CNC Energy Intelligence Platform

**Date**: 2026-05-15
**run_id**: `b534eab9-c8b5-4a2f-bad1-8cb75bb00e40`
**Script**: `src/gold/build.py`
**Input**: 18 Silver Parquet files (55 cols each) + `train_silver.parquet`
**Output**: 123-column Gold feature store

---

## What each step did

### Step 1 -- Defect removal
Dropped all rows where `defect_feedrate_50 = True` OR `defect_position_198 = True` (union, not intersection). The column `defect_program_nonzero` was dropped entirely from the clean frame (97.2% True = zero discriminative signal). Dropped rows were saved to `diagnostics/defect_rows.parquet` for audit.

### Step 2 -- Metadata join
Loaded `train_silver.parquet` (18 rows x 8 cols). Matched each experiment by the `No` column (experiment_01 = No 1, etc.). Encoded:
- `tool_condition_enc`: unworn=0, worn=1
- `machining_finalized_enc`: no=0, yes=1
- `passed_visual_inspection_enc`: no=0, yes=1, NaN=-1

Five metadata columns broadcast to every row of the experiment: `feedrate`, `clamp_pressure`, and the three encoded columns.

### Step 3 -- Phase encoding
Normalised lowercase `end` -> `End` (found in experiment_01's Silver output). Mapped `Machining_Process` to `phase_id` (ordinal 0-9). Added `is_cutting_phase` (True for phase_id 2-7, i.e. Layer X Up/Down). Used a contiguous-block approach (`cumsum` on phase transitions) to compute `phase_row_index` (0-based position within block) and `phase_duration_rows` (total rows in block). This correctly handles Repositioning appearing multiple times in a single experiment.

### Step 4 -- Lag features
Applied `shift(n)` per experiment (function called on a single-experiment dataframe at a time). Produced 5 lags x 4 columns = 20 lag features. NaN head rows from lag-60 remain as NaN (no imputation -- they carry valid missingness signal for the ML layer).

### Step 5 -- Rolling window features
Applied `rolling(window, min_periods=1)` per experiment. Used `min_periods=1` so early rows are not discarded. Produced 7 stat/window combinations x 4 columns = 28 rolling features.

### Step 6 -- Phase aggregations
Reconstructed contiguous phase blocks (same `cumsum` logic as Step 3). Computed `_total_power_row = X1+Y1+S1 OutputPower` as an intermediate. Used `groupby('_phase_block').transform(agg)` to broadcast `phase_power_total`, `phase_power_mean`, `phase_power_peak` and `phase_energy_kwh` to every row of the block.

### Step 7 -- Cross features
Four purely arithmetic features: `total_output_power`, `power_spindle_ratio`, `xy_power_ratio`, `velocity_magnitude_xy`. All applied on the per-experiment dataframe before global concatenation.

### Step 8 -- Target construction
Shifted `total_output_power` by -10 and -30 rows (per experiment) to produce `target_power_next_1s` and `target_power_next_3s`. Dropped the 30 NaN tail rows per experiment (shift -30 is the binding constraint). Exactly 540 rows dropped across 18 experiments (30 per experiment, consistent).

### Step 9 -- Split and export
Split by experiment number on the final per-experiment Gold frames. Exported the three split files, 18 per-experiment files, the diagnostics file, and the feature registry.

---

## Final column count

**123 columns** total in Gold (121 features + 2 targets).

---

## Row counts per split

| Split | Experiments | Rows |
|---|---|---|
| Train | 01-14 | 12,398 |
| Validation | 15-16 | 1,042 |
| Test | 17-18 | 3,875 |
| **Total Gold** | 01-18 | **17,315** |

---

## Defect removal stats

| Metric | Value |
|---|---|
| Silver total rows | 25,286 |
| Defect rows dropped | 7,431 |
| Pct of total dropped | 29.4% |
| After defect removal | 17,855 |
| After target tail drop (30/exp) | 17,315 |

### Per-experiment breakdown

| Experiment | Silver rows | Defects dropped | After defect | Gold rows | Pct dropped |
|---|---|---|---|---|---|
| experiment_01 | 1,055 | 64 | 991 | 961 | 6.1% |
| experiment_02 | 1,668 | 1,383 | 285 | 255 | 82.9% |
| experiment_03 | 1,521 | 528 | 993 | 963 | 34.7% |
| experiment_04 | 532 | 385 | 147 | 117 | 72.4% |
| experiment_05 | 462 | 414 | 48 | 18 | 89.6% |
| experiment_06 | 1,296 | 305 | 991 | 961 | 23.5% |
| experiment_07 | 565 | 309 | 256 | 226 | 54.7% |
| experiment_08 | 605 | 281 | 324 | 294 | 46.4% |
| experiment_09 | 740 | 322 | 418 | 388 | 43.5% |
| experiment_10 | 1,301 | 789 | 512 | 482 | 60.6% |
| experiment_11 | 2,314 | 349 | 1,965 | 1,935 | 15.1% |
| experiment_12 | 2,276 | 315 | 1,961 | 1,931 | 13.8% |
| experiment_13 | 2,233 | 272 | 1,961 | 1,931 | 12.2% |
| experiment_14 | 2,332 | 366 | 1,966 | 1,936 | 15.7% |
| experiment_15 | 1,381 | 385 | 996 | 966 | 27.9% |
| experiment_16 | 602 | 496 | 106 | 76 | 82.4% |
| experiment_17 | 2,150 | 182 | 1,968 | 1,938 | 8.5% |
| experiment_18 | 2,253 | 286 | 1,967 | 1,937 | 12.7% |

> Notable: experiments 02, 05, and 16 lost >80% of rows to defects. Experiment 05 exits Gold with only 18 rows -- too small for reliable model training. ML team should flag this experiment.

---

## Data surprises vs the spec

1. **Lowercase `end` phase label** -- The Silver transform stored `end` (lowercase) for experiment_01 while all other experiments use `End` (capitalised). Handled by a `replace({"end": "End"})` normalisation step before phase encoding. The Silver VALID_MACHINING_PROCESS set had stored it as `"end"` which is why it passed through. All Gold files use consistent `End`.

2. **Defect union semantics in experiment_02** -- Silver shows 1,292 feedrate_50 rows + 1,206 position_198 rows for experiment_02 (total 2,498 flags), yet only 1,383 rows were dropped. This means 115 rows had both defects active simultaneously. The union `(defect_feedrate_50 | defect_position_198)` correctly deduplicates them.

3. **Experiment_05 near-total data loss** -- 414 of 462 rows (89.6%) are defective. Only 18 Gold rows remain. The spec said to log this but not to exclude the experiment. The 18 rows are exported and included in the train split.

4. **48 source columns, not 53** -- Confirmed at Gold time: Z1 has no OutputPower column. The source list in the feature registry reflects 48 sensor columns accordingly.

5. **`End` and `Repositioning` phases present** -- Both treated as valid phases with IDs 8 and 9 as specified. They appear in most experiments. Repositioning can appear multiple times non-contiguously; the contiguous-block logic handles this correctly.

6. **Target drop is exactly 30 rows per experiment** -- The binding constraint is `shift(-30)` for the 3-second target. All 18 experiments lose exactly 30 tail rows. Total target drops = 540 rows.

---

## Full feature list by category

### Infrastructure / traceability (2)
`experiment_id`, `gold_run_id`

### Source sensor columns -- pass-through from Silver (48)
X1: `X1_ActualPosition`, `X1_ActualVelocity`, `X1_ActualAcceleration`, `X1_CommandPosition`, `X1_CommandVelocity`, `X1_CommandAcceleration`, `X1_CurrentFeedback`, `X1_DCBusVoltage`, `X1_OutputCurrent`, `X1_OutputVoltage`, `X1_OutputPower`

Y1: `Y1_ActualPosition`, `Y1_ActualVelocity`, `Y1_ActualAcceleration`, `Y1_CommandPosition`, `Y1_CommandVelocity`, `Y1_CommandAcceleration`, `Y1_CurrentFeedback`, `Y1_DCBusVoltage`, `Y1_OutputCurrent`, `Y1_OutputVoltage`, `Y1_OutputPower`

Z1 (no OutputPower): `Z1_ActualPosition`, `Z1_ActualVelocity`, `Z1_ActualAcceleration`, `Z1_CommandPosition`, `Z1_CommandVelocity`, `Z1_CommandAcceleration`, `Z1_CurrentFeedback`, `Z1_DCBusVoltage`, `Z1_OutputCurrent`, `Z1_OutputVoltage`

S1: `S1_ActualPosition`, `S1_ActualVelocity`, `S1_ActualAcceleration`, `S1_CommandPosition`, `S1_CommandVelocity`, `S1_CommandAcceleration`, `S1_CurrentFeedback`, `S1_DCBusVoltage`, `S1_OutputCurrent`, `S1_OutputVoltage`, `S1_OutputPower`, `S1_SystemInertia`

M1: `M1_CURRENT_PROGRAM_NUMBER`, `M1_sequence_number`, `M1_CURRENT_FEEDRATE`

Phase label: `Machining_Process`

### Silver quality flags -- retained in Gold (6)
`timestamp_ms`, `defect_feedrate_50`, `defect_position_198`, `missing_power`, `interpolated`, `validation_run_id`

> Note: `defect_program_nonzero` was dropped (no signal).

### Metadata features -- broadcast from train.csv (5)
`feedrate`, `clamp_pressure`, `tool_condition_enc`, `machining_finalized_enc`, `passed_visual_inspection_enc`

### Phase encoding features (4)
`phase_id`, `is_cutting_phase`, `phase_row_index`, `phase_duration_rows`

### Lag features -- 4 columns x 5 lags = 20 (20)
`X1_OutputPower_lag_1/5/10/30/60`
`Y1_OutputPower_lag_1/5/10/30/60`
`S1_OutputPower_lag_1/5/10/30/60`
`M1_CURRENT_FEEDRATE_lag_1/5/10/30/60`

### Rolling features -- 4 columns x 7 stat/window combinations = 28 (28)
`X1_OutputPower_roll10_mean/std/min/max`, `X1_OutputPower_roll30_mean/std`, `X1_OutputPower_roll60_mean`
`Y1_OutputPower_roll10_mean/std/min/max`, `Y1_OutputPower_roll30_mean/std`, `Y1_OutputPower_roll60_mean`
`S1_OutputPower_roll10_mean/std/min/max`, `S1_OutputPower_roll30_mean/std`, `S1_OutputPower_roll60_mean`
`M1_CURRENT_FEEDRATE_roll10_mean/std/min/max`, `M1_CURRENT_FEEDRATE_roll30_mean/std`, `M1_CURRENT_FEEDRATE_roll60_mean`

### Phase aggregation features (4)
`phase_power_total`, `phase_power_mean`, `phase_power_peak`, `phase_energy_kwh`

### Cross features (4)
`total_output_power`, `power_spindle_ratio`, `xy_power_ratio`, `velocity_magnitude_xy`

### Targets (2)
`target_power_next_1s` (shift -10 rows = 1s ahead)
`target_power_next_3s` (shift -30 rows = 3s ahead)

---

## Feature Descriptions (new features added in Gold)

### Metadata features (5)
| Feature | Description |
|---|---|
| `feedrate` | Speed at which the cutting tool moves through the material (mm/min). Set before the experiment starts. |
| `clamp_pressure` | Pressure used to hold the wax block in place (bar). Higher pressure = more stable cut. |
| `tool_condition_enc` | Whether the cutting tool is new (0=unworn) or degraded (1=worn). Key variable for predicting quality. |
| `machining_finalized_enc` | Whether the experiment completed fully (1=yes) or was stopped early (0=no). |
| `passed_visual_inspection_enc` | Result of manual quality check after machining: 1=pass, 0=fail, -1=not checked (machining not finalized). |

### Phase encoding features (4)
| Feature | Description |
|---|---|
| `phase_id` | The current machining phase as a number (0=Starting, 1=Prep, 2=Layer 1 Up, 3=Layer 1 Down, 4=Layer 2 Up, 5=Layer 2 Down, 6=Layer 3 Up, 7=Layer 3 Down, 8=End, 9=Repositioning). |
| `is_cutting_phase` | True when the machine is actively cutting material (phases 2-7). False during setup, repositioning, and end. |
| `phase_row_index` | How many rows have passed since the current phase started. Tells the model how far into a phase we are. |
| `phase_duration_rows` | Total length of the current phase in rows. Gives the model context on the full duration of the phase. |

### Lag features (20) — 5 lags x 4 columns
The 4 columns are: X1_OutputPower, Y1_OutputPower, S1_OutputPower, M1_CURRENT_FEEDRATE

| Feature pattern | Description |
|---|---|
| `{col}_lag_1` | Value of the column 1 step ago (100ms ago). Captures what just happened. |
| `{col}_lag_5` | Value 5 steps ago (500ms ago). Short-term memory. |
| `{col}_lag_10` | Value 10 steps ago (1 second ago). |
| `{col}_lag_30` | Value 30 steps ago (3 seconds ago). Medium-term trend. |
| `{col}_lag_60` | Value 60 steps ago (6 seconds ago). Longer-term context. |

> Example: `X1_OutputPower_lag_10` = what was the X-axis power 1 second ago?

### Rolling window features (28) — 4 columns x 7 stat/window combinations
| Feature pattern | Description |
|---|---|
| `{col}_roll10_mean` | Average value over the last 1 second (10 rows). Smooths out noise. |
| `{col}_roll10_std` | How much the value varied over the last 1 second. High std = unstable machine. |
| `{col}_roll10_min` | Lowest value seen in the last 1 second. |
| `{col}_roll10_max` | Highest value seen in the last 1 second. |
| `{col}_roll30_mean` | Average over the last 3 seconds. Captures medium-term trend. |
| `{col}_roll30_std` | Variability over the last 3 seconds. |
| `{col}_roll60_mean` | Average over the last 6 seconds. Long-term baseline for the current phase. |

> Example: `S1_OutputPower_roll10_std` = how stable has the spindle power been in the last second?

### Phase aggregation features (4)
| Feature | Description |
|---|---|
| `phase_power_total` | Total energy (sum of X1+Y1+S1 power) consumed during the entire current phase. |
| `phase_power_mean` | Average power consumed during the entire current phase. |
| `phase_power_peak` | Maximum power spike recorded during the entire current phase. |
| `phase_energy_kwh` | Energy in kilowatt-hours consumed by the current phase (phase_power_mean x duration x 0.1s / 3600). |

> These are broadcast: every row in a phase carries the same aggregate values for that phase.

### Cross features (4)
| Feature | Description |
|---|---|
| `total_output_power` | Sum of X1 + Y1 + S1 output power. Total electrical power consumed by all 3 active axes at this instant. |
| `power_spindle_ratio` | Share of total power consumed by the spindle (S1). High ratio = spindle-dominant operation. |
| `xy_power_ratio` | Ratio of X-axis power to Y-axis power. Indicates which horizontal axis is working harder. |
| `velocity_magnitude_xy` | Combined speed of the X and Y axes (Euclidean norm). Represents the true cutting speed in the horizontal plane. |

### Targets (2)
| Feature | Description |
|---|---|
| `target_power_next_1s` | Total output power 1 second into the future (10 rows ahead). This is what the model learns to predict. |
| `target_power_next_3s` | Total output power 3 seconds into the future (30 rows ahead). Longer-horizon prediction target. |

---

## Key implementation decisions

1. **Contiguous block approach for phases** -- The spec says `groupby(['experiment_id', 'phase_id'])` but this would merge non-adjacent occurrences of Repositioning into one aggregate. The implementation uses a `cumsum` on phase transitions to assign a unique `_phase_block` ID per contiguous run, then aggregates over that. This is strictly correct and the feature values will differ from a naive `phase_id` groupby when Repositioning repeats.

2. **`min_periods=1` on rolling windows** -- The spec does not specify this. Without it, the first `window-1` rows per experiment would be NaN (e.g. 59 NaN rows per experiment for `roll60_mean`). With `min_periods=1`, the window expands from row 0. This avoids discarding additional rows but means early roll60 values are computed over fewer than 60 samples. Acceptable for the ML use case.

3. **Lag NaN head rows retained** -- Rows with NaN lag values (e.g. first 60 rows have `lag_60 = NaN`) are NOT dropped. This is intentional: the ML model will handle them (e.g. impute or mask). Dropping them would remove the early portion of every phase from the training set.

4. **`defect_program_nonzero` dropped from clean frame only** -- The full Silver column is preserved in `defect_rows.parquet` for diagnostic traceability. It is dropped only from the feature-engineered Gold frames.

5. **Idempotency guard** -- If all required Gold outputs (train/val/test parquets, feature_registry.json, defect_rows.parquet) are newer than all Silver inputs, the script exits early with no side effects. Delete `data/gold/` to force a full rebuild.

6. **`passed_visual_inspection` missing -> -1** -- Experiments 4, 5, 7, 16 have NaN for this column (machining not finalised). Encoded as -1 rather than 0 to make the missingness explicit and distinguishable from "no" (0) for the ML model.
