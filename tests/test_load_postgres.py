"""Integration test against a real Postgres. Skipped unless TEST_DATABASE_URL is set."""
import os
from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from src.clean import clean_sales
from src.load_postgres import load_to_postgres

URL = os.environ.get("TEST_DATABASE_URL", "").replace("postgresql://", "postgresql+psycopg2://", 1) or None
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


def make(rows):
    df, report = clean_sales(pd.DataFrame(rows))
    df["source_file"] = "t.csv"
    df["ingested_at"] = datetime.now(timezone.utc)
    return df, report


def row(oid, profit="100"):
    return {"Order ID": oid, "Order Date": "2026-09-01", "Region": "North", "Category": "Furniture",
            "Sub-Category": "Chairs", "Quantity": "1", "Unit Price": "1000", "Sales": "1000", "Profit": profit}


def test_upsert_is_idempotent_and_updates():
    eng = create_engine(URL)
    with eng.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS sales_clean, pipeline_runs"))

    df, rep = make([row("A"), row("B")])
    load_to_postgres(df, URL, rep, "t.csv")
    df, rep = make([row("B", profit="250"), row("C")])   # B re-sent with a correction
    load_to_postgres(df, URL, rep, "t2.csv")

    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM sales_clean")).scalar() == 3
        assert c.execute(text("SELECT profit FROM sales_clean WHERE order_id='B'")).scalar() == 250
        assert c.execute(text("SELECT COUNT(*) FROM pipeline_runs")).scalar() == 2
