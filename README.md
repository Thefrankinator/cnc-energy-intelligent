# CNC Energy Intelligent

Intelligent platform for predicting and monitoring energy consumption of CNC milling machines.

Built as a 3-week team project (5 people, 5 modules) in the Big Data / Data Science / AI program.

---

## Architecture — Medallion Pipeline

```
dataset/ (19 CSV source files)
        |
        v
    BRONZE  — Immutable copy, DVC versioning, MD5 manifest
        |
        v
    SILVER  — Schema validation, defect flagging, NaN handling, quality reports
        |
        v
     GOLD   — Full feature store (123 columns), ready for ML
        |
        v
   [ML / API / Dashboard]
```

| Layer | Format | Content |
|-------|--------|---------|
| **Bronze** | CSV (unchanged) | Exact copy of 19 source files, immutable, DVC-versioned |
| **Silver** | Parquet | 48 sensor cols + 6 quality flags (defects flagged, not removed) |
| **Gold** | Parquet | 121 features + 2 targets (`target_power_next_1s`, `target_power_next_3s`) |

**Key design choices:**
- Defects: flagged in Silver, removed from Gold training set (kept in `diagnostics/`)
- Split: Exp. 01–14 (train, 12,398 rows) / 15–16 (val, 1,042 rows) / 17–18 (test, 3,875 rows)
- See `dataops_pipeline.md` for full pipeline design

---

## Dataset

**CNC Milling Dataset** — University of Michigan SMART Lab (2018)

- 18 milling experiments on wax blocks
- 48 sensor columns at 100ms intervals (X/Y/Z axes, spindle, program metadata)
- Metadata: feedrate (3–20 mm/s), clamp pressure (2.5–4.0 bar), tool condition (worn/unworn)
- See `dataset_info.md` for full column documentation

---

## Team Modules

| Module | Responsibility |
|--------|---------------|
| Data Pipeline | ETL + DVC + Feature Store |
| ML | Supervised model + anomaly detection + MLflow |
| MLOps | Automated retraining + CI + monitoring |
| Backend | FastAPI + anomaly logic + human feedback |
| Frontend | Streamlit dashboard + human validation |

---

## Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Prediction model | LightGBM / XGBoost / Prophet |
| Anomaly detection | Isolation Forest (scikit-learn) |
| Data versioning | DVC |
| Experiment tracking | MLflow |
| Drift monitoring | Evidently |
| API | FastAPI |
| Dashboard | Streamlit |
| Containerization | Docker / Docker Compose |
| Tests | pytest |

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/Thefrankinator/cnc-energy-intelligent.git
cd cnc-energy-intelligent

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Pull data from DVC remote (requires access to shared DVC remote)
dvc pull
```

---

## Reproduce the Pipeline

```bash
# Run the full DataOps pipeline (Bronze → Silver → Gold)
dvc repro

# Check pipeline status
dvc status
```

Pipeline stages (defined in `dvc.yaml`):

| Stage | Command | Input → Output |
|-------|---------|----------------|
| `clean` | `python src/silver/transform.py` | Bronze CSVs → Silver Parquets |
| `featurize` | `python src/gold/build.py` | Silver Parquets → Gold feature store |

---

## Repo Structure

```
cnc-energy-intelligent/
├── README.md
├── requirements.txt
├── dvc.yaml                        # DVC pipeline definition
├── dvc.lock                        # Locked pipeline state
├── _context.md                     # Project context (read first)
├── dataops_pipeline.md             # DataOps design doc
├── dataset_info.md                 # Dataset documentation
├── cahier_des_charges_cnc_v2.pdf   # Project specification v2.0
│
├── src/                            # Python source code
│   ├── bronze/ingest.py            # Bronze ingestion
│   ├── silver/transform.py         # Silver validation & cleaning
│   └── gold/build.py               # Gold feature engineering
│
└── data/
    ├── bronze.dvc                  # DVC pointer (bronze data on remote)
    ├── bronze/
    │   ├── bronze_recap.md         # Bronze layer documentation
    │   └── ingestion_log.jsonl     # Append-only ingestion log
    ├── silver/quality/
    │   ├── quality_report_analysis.md
    │   └── quality_summary.csv
    └── gold/
        ├── gold_recap.md           # Gold layer documentation
        └── feature_registry.json   # 123-feature metadata registry
```

> **Data files** (CSVs, Parquets) are managed by DVC and not stored in this repo.
> Run `dvc pull` to download them after cloning.

---

## DataOps Status

| Layer | Status | Details |
|-------|--------|---------|
| Bronze | **Done** | 19 files ingested, DVC-versioned, idempotent |
| Silver | **Done** | 18 experiments × 55 cols, 3 defect flags, quality reports |
| Gold | **Done** | 17,315 rows, 123 columns, train/val/test split |

---

## Documents

- `cahier_des_charges_cnc_v2.pdf` — Full project specification v2.0
- `_context.md` — Project context, architecture decisions, team organization
- `dataops_pipeline.md` — DataOps Medallion pipeline design with progress tracking
- `dataset_info.md` — Complete dataset documentation (columns, axes, objectives)
- `data/gold/feature_registry.json` — Metadata for all 123 Gold features
