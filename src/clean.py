"""Cleaning logic for raw sales CSVs.

Every step is counted in a report dict so each pipeline run logs exactly
what was fixed or dropped (shown in the GitHub Actions job summary).
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = [
    "order_id", "order_date", "region", "category", "sub_category",
    "quantity", "unit_price", "sales", "profit",
]
TEXT_COLUMNS = ["region", "category", "sub_category"]
NUMERIC_COLUMNS = ["quantity", "unit_price", "sales", "profit"]


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """'Order Date ' -> 'order_date', 'Sub-Category' -> 'sub_category'."""
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    return df


def to_number(s: pd.Series) -> pd.Series:
    """Parse numbers stored as text, e.g. '₹1,250.00' or ' 34 '."""
    cleaned = s.astype("string").str.replace(r"[₹$,\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def clean_sales(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report: dict[str, int] = {"rows_in": len(raw)}
    df = standardize_columns(raw.copy())

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    df = df[REQUIRED_COLUMNS]

    # 1. Types: text, numbers, dates
    df["order_id"] = df["order_id"].astype("string").str.strip().str.upper()
    for col in TEXT_COLUMNS:
        df[col] = df[col].astype("string").str.strip().str.title()
    for col in NUMERIC_COLUMNS:
        df[col] = to_number(df[col])
    df["order_date"] = pd.to_datetime(
        df["order_date"].astype("string").str.strip(), format="mixed", errors="coerce"
    )

    # 2. Duplicates: exact copies first, then repeated order IDs
    before = len(df)
    df = df.drop_duplicates()
    report["exact_duplicates_removed"] = before - len(df)
    before = len(df)
    df = df.drop_duplicates(subset="order_id", keep="first")
    report["duplicate_order_ids_removed"] = before - len(df)

    # 3. Rows that can't be recovered
    before = len(df)
    df = df.dropna(subset=["order_id", "order_date"])
    df = df[df["order_id"] != ""]
    report["missing_id_or_date_dropped"] = before - len(df)

    # 4. Fill numbers that can be derived from the others
    q, p, s = df["quantity"], df["unit_price"], df["sales"]
    fill_sales = s.isna() & q.notna() & p.notna()
    df.loc[fill_sales, "sales"] = q[fill_sales] * p[fill_sales]
    fill_qty = df["quantity"].isna() & df["sales"].notna() & p.notna() & (p > 0)
    df.loc[fill_qty, "quantity"] = (df.loc[fill_qty, "sales"] / p[fill_qty]).round()
    fill_price = df["unit_price"].isna() & df["sales"].notna() & (df["quantity"] > 0)
    df.loc[fill_price, "unit_price"] = df.loc[fill_price, "sales"] / df.loc[fill_price, "quantity"]
    report["values_derived"] = int(fill_sales.sum() + fill_qty.sum() + fill_price.sum())

    # 5. Missing categories -> 'Unknown' (keeps the revenue in totals)
    report["missing_text_filled"] = int(df[TEXT_COLUMNS].isna().sum().sum())
    df[TEXT_COLUMNS] = df[TEXT_COLUMNS].fillna("Unknown")

    # 6. Invalid or still-incomplete numeric rows
    before = len(df)
    df = df.dropna(subset=["quantity", "unit_price", "sales"])
    df = df[(df["quantity"] > 0) & (df["unit_price"] > 0) & (df["sales"] >= 0)]
    report["invalid_numeric_dropped"] = before - len(df)

    # 7. Missing profit -> sales x median margin of that category (flagged)
    df["profit_imputed"] = df["profit"].isna()
    margin = (df["profit"] / df["sales"]).where(df["sales"] > 0)
    cat_margin = margin.groupby(df["category"]).transform("median").fillna(margin.median())
    df.loc[df["profit_imputed"], "profit"] = (df["sales"] * cat_margin)[df["profit_imputed"]]
    report["profit_imputed"] = int(df["profit_imputed"].sum())

    # 8. Final types and derived columns for analysis
    df["quantity"] = df["quantity"].astype("int64")
    for col in ["unit_price", "sales", "profit"]:
        df[col] = df[col].astype("float64").round(2)
    df["order_month"] = df["order_date"].dt.to_period("M").dt.to_timestamp()
    df["profit_margin"] = (df["profit"] / df["sales"]).where(df["sales"] > 0).round(4)

    report["rows_out"] = len(df)
    return df.reset_index(drop=True), report
