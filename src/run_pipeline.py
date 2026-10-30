"""Run the SQL layers in order against DuckDB and export the golden dataset.
Usage: python src/run_pipeline.py [--data data] [--db golden/collections.duckdb]"""
import argparse, pathlib, duckdb, json

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAYERS = ["00_staging", "01_clean", "02_golden", "03_metrics", "04_forensics"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--db", default=str(ROOT / "golden" / "collections.duckdb"))
    a = ap.parse_args()
    db = pathlib.Path(a.db); db.parent.mkdir(exist_ok=True)
    if db.exists(): db.unlink()
    con = duckdb.connect(str(db))
    for layer in LAYERS:
        f = ROOT / "sql" / f"{layer}.sql"
        if not f.exists(): continue
        con.execute(f.read_text().replace("${DATA_DIR}", str(pathlib.Path(a.data).resolve())))
        print(f"ran {f.name}")
    out = ROOT / "golden"
    for t in ["dim_account","dim_agent","dim_campaign","dim_vendor","fact_payment","fact_ptp","fact_target","fact_contact","account_month"]:
        con.execute(f"copy golden.{t} to '{out}/{t}.parquet' (format parquet, compression zstd)")
    con.execute(f"copy dq.rule_log to '{out}/dq_rule_log.csv' (header)")
    print(con.sql("select * from dq.rule_log").df().to_string())
if __name__ == "__main__":
    main()
