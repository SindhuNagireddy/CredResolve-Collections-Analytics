# CredResolve Collections Analytics

Independent reconstruction of collections recovery from the supplied multi-system dataset. The project combines a DuckDB SQL pipeline, a reproducible Python investigation, a one-screen executive dashboard, a data-quality report, an executive memo, and a production architecture design.

## Main deliverables

- `sql/00_staging.sql` — raw staging and source-row lineage
- `sql/01_clean.sql` — deduplication, timezone normalization, and rejected rows
- `sql/02_golden.sql` — trusted analytical entities and event facts
- `sql/03_metrics.sql` — recovery, contact, PTP, and channel metrics
- `sql/04_forensics.sql` — duplicate, attribution, timezone, vendor, identity, mix, and denominator audits
- `src/run_pipeline.py` — builds the DuckDB layers and exports golden Parquet datasets
- `src/run_analysis.py` — standalone Python analysis from the raw CSVs
- `notebooks/collections_analysis.ipynb` — analysis reasoning, results, and limitations
- `reports/dashboard.html` — self-contained executive dashboard (open in a browser)
- `reports/executive_memo.md` — executive memo
- `reports/data_quality_summary.csv` — quantified DQ summary\n- `reports/targeting_denominator_audit.csv`, `reports/first_target_cohort_30d.csv`, `reports/survivorship_status_audit.csv` — selection, cohort, and denominator sensitivity
- `reports/monthly_recovery.csv` — monthly metrics and partial-month flags
- `reports/architecture.svg` — rendered production architecture diagram\n- `reports/architecture.mmd` — production architecture diagram in Mermaid syntax\n- `reports/production_analytics_design.md` — contracts, keys, metrics, backfills, monitoring and counterfactual design

## Setup

Use Python 3.12+ if you encounter package compatibility issues. Python 3.14 may work with the installed versions of the dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Unzip the supplied dataset and copy all CSV files directly into `data/` (do not nest them in another folder). The raw CSVs are intentionally excluded from Git.

## Run the SQL pipeline

```bash
python src/run_pipeline.py
```

This creates `golden/collections.duckdb`, exports the trusted Parquet datasets, and prints the SQL data-quality rule log.

## Run the Python analysis and dashboard

```bash
python src/run_analysis.py --data data --out reports
```

Then open `reports/dashboard.html` in a browser. The notebook can be opened in VS Code or Jupyter; run it from the project root so its relative paths resolve.

## Key working conclusion

Under the documented independent definition—deduplicate by `payment_id`, count only `SUCCESS`, assign payment month after provider-timezone conversion to IST, and normalize by observed days—January-to-July recovery per day changed by approximately **+0.09%**. This does not substantiate a sustained +11% month-on-month claim. August is only observed through 8 August. See the memo for evidence levels and caveats.

## Important limitations

- The data extract covers January–8 August 2026, not 12 complete months.
- `SUCCESS` is a provisional proxy for recovered cash until reconciled against settlement and reversal ledgers.
- Current account attributes may not represent historical state at payment time.
- A targeting event is not proof of contact or causation.
- Channel associations in observational data do not establish causal lift or investment ROI.

## Git hygiene

Do not commit `.venv/`, raw CSVs, local database files, API credentials, or personal information. Inspect `git status` before pushing.
