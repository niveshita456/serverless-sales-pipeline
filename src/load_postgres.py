"""Load cleaned sales data into PostgreSQL (Supabase free tier or any Postgres).

Each file is loaded in ONE transaction:
  1. write rows to a temporary staging table
  2. UPSERT into sales_clean (insert new orders, update re-sent ones)
  3. record the run's data-quality report in pipeline_runs
If anything fails, nothing is written: no half-loaded files.
"""
from __future__ import annotations

import json
import re

import pandas as pd
from sqlalchemy import create_engine, text

COLUMNS = [
    "order_id", "order_date", "order_month", "region", "category", "sub_category",
    "quantity", "unit_price", "sales", "profit", "profit_margin", "profit_imputed",
    "source_file", "ingested_at",
]

DDL = """
CREATE TABLE IF NOT EXISTS sales_clean (
    order_id        TEXT PRIMARY KEY,
    order_date      DATE NOT NULL,
    order_month     DATE NOT NULL,
    region          TEXT NOT NULL,
    category        TEXT NOT NULL,
    sub_category    TEXT NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(12, 2) NOT NULL,
    sales           NUMERIC(14, 2) NOT NULL,
    profit          NUMERIC(14, 2) NOT NULL,
    profit_margin   NUMERIC(8, 4),
    profit_imputed  BOOLEAN NOT NULL DEFAULT FALSE,
    source_file     TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sales_month  ON sales_clean (order_month);
CREATE INDEX IF NOT EXISTS idx_sales_region ON sales_clean (region, category);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    source_file  TEXT NOT NULL,
    rows_in      INTEGER,
    rows_out     INTEGER,
    rows_upserted INTEGER,
    report       JSONB,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

UPSERT = f"""
INSERT INTO sales_clean ({", ".join(COLUMNS)})
SELECT order_id, order_date::date, order_month::date, region, category, sub_category,
       quantity, unit_price, sales, profit, profit_margin, profit_imputed,
       source_file, ingested_at
FROM _staging_sales
ON CONFLICT (order_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "order_id")}
"""


def get_engine(url: str):
    # Supabase gives "postgres://..."; pin the psycopg2 driver explicitly
    url = re.sub(r"^postgres(ql)?://", "postgresql+psycopg2://", url)
    return create_engine(url, pool_pre_ping=True)


def load_to_postgres(df: pd.DataFrame, url: str, report: dict, source_file: str) -> int:
    engine = get_engine(url)
    with engine.begin() as conn:  # one transaction: all or nothing
        conn.execute(text(DDL))
        df[COLUMNS].to_sql("_staging_sales", conn, if_exists="replace", index=False)
        upserted = conn.execute(text(UPSERT)).rowcount
        conn.execute(text("DROP TABLE _staging_sales"))
        conn.execute(
            text("""INSERT INTO pipeline_runs (source_file, rows_in, rows_out, rows_upserted, report)
                    VALUES (:f, :i, :o, :u, CAST(:r AS JSONB))"""),
            {"f": source_file, "i": report["rows_in"], "o": report["rows_out"],
             "u": upserted, "r": json.dumps(report, default=str)},
        )
    engine.dispose()
    return upserted
