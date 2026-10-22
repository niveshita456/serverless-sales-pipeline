"""Pipeline entry point.

    python -m src.pipeline data/incoming/sales_2026_10.csv            # clean + load to PostgreSQL
    python -m src.pipeline data/incoming/sales_2026_10.csv --dry-run  # clean only, write CSV locally

Config: DATABASE_URL environment variable (Postgres connection string).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.clean import clean_sales


def write_summary(lines: list[str]) -> None:
    """Append to the GitHub Actions job summary when running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def process_file(path: Path, dry_run: bool, out_dir: Path) -> dict:
    raw = pd.read_csv(path, dtype=str, keep_default_na=True)
    df, report = clean_sales(raw)
    df["source_file"] = path.name
    df["ingested_at"] = datetime.now(timezone.utc)

    if dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{path.stem}_clean.csv"
        df.to_csv(out_path, index=False)
        report["output"] = str(out_path)
    else:
        from src.load_postgres import load_to_postgres

        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        report["rows_upserted"] = load_to_postgres(df, url, report, path.name)
        report["output"] = "postgres: sales_clean"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean sales CSVs and load to PostgreSQL")
    parser.add_argument("files", nargs="*", help="CSV files to process")
    parser.add_argument("--dry-run", action="store_true", help="Clean only; write CSVs locally")
    parser.add_argument("--out-dir", default="data/processed", help="Output folder for --dry-run")
    args = parser.parse_args(argv)

    files = [Path(f) for f in args.files if f.strip()]
    if not files:
        print("No new CSV files to process.")
        return 0

    summary = ["## Sales pipeline run", "", "| File | Rows in | Rows out | Duplicates | Derived | Imputed profit | Dropped | Output |",
               "|---|---|---|---|---|---|---|---|"]
    failed = False
    for path in files:
        try:
            r = process_file(path, args.dry_run, Path(args.out_dir))
        except Exception as exc:  # report every file, fail the run at the end
            failed = True
            print(f"FAILED {path}: {exc}", file=sys.stderr)
            summary.append(f"| {path.name} | – | – | – | – | – | – | ❌ {exc} |")
            continue
        print(json.dumps({"file": str(path), **r}, default=str))
        dupes = r["exact_duplicates_removed"] + r["duplicate_order_ids_removed"]
        dropped = r["missing_id_or_date_dropped"] + r["invalid_numeric_dropped"]
        summary.append(
            f"| {path.name} | {r['rows_in']} | {r['rows_out']} | {dupes} | {r['values_derived']} "
            f"| {r['profit_imputed']} | {dropped} | `{r['output']}` |"
        )
    write_summary(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
