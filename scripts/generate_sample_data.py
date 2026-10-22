"""Generate a realistic, deliberately messy sales CSV for testing the pipeline.

    python scripts/generate_sample_data.py --rows 2000 --month 2026-09 --out data/incoming/sales_2026_09.csv

Injected problems: duplicate rows, repeated order IDs, missing values,
currency symbols and commas in numbers, inconsistent casing/spaces,
two date formats, and a few negative/zero quantities.
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

CATALOG = {
    "Technology": {"Phones": (8000, 45000, 0.12), "Laptops": (35000, 120000, 0.09), "Accessories": (300, 4000, 0.25)},
    "Furniture": {"Chairs": (2500, 18000, 0.10), "Tables": (5000, 30000, 0.06), "Bookcases": (3000, 15000, -0.02)},
    "Office Supplies": {"Paper": (100, 900, 0.30), "Binders": (80, 600, 0.28), "Storage": (500, 5000, 0.15)},
}
REGIONS = {"North": 1.0, "South": 1.2, "East": 0.8, "West": 1.1}


def generate(rows: int, month: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    random.seed(seed)
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    days = (date(year + mon // 12, mon % 12 + 1, 1) - start).days

    records = []
    for i in range(rows):
        category = rng.choice(list(CATALOG))
        sub = rng.choice(list(CATALOG[category]))
        lo, hi, margin = CATALOG[category][sub]
        region = rng.choice(list(REGIONS), p=np.array(list(REGIONS.values())) / sum(REGIONS.values()))
        qty = int(rng.integers(1, 8))
        price = round(float(rng.uniform(lo, hi)), 2)
        sales = round(qty * price * float(rng.uniform(0.9, 1.0)), 2)  # small discounts
        profit = round(sales * (margin + float(rng.normal(0, 0.05))), 2)
        d = start + timedelta(days=int(rng.integers(0, days)))
        records.append({
            "Order ID": f"ORD-{year}{mon:02d}-{i:05d}",
            "Order Date": d.isoformat(),
            "Region": region, "Category": category, "Sub-Category": sub,
            "Quantity": str(qty), "Unit Price": str(price), "Sales": str(sales), "Profit": str(profit),
        })
    df = pd.DataFrame(records)

    def pick(frac):
        return df.sample(frac=frac, random_state=int(rng.integers(1e9))).index

    df.loc[pick(0.05), "Region"] = df["Region"].str.lower() + "  "          # casing / spaces
    df.loc[pick(0.03), "Category"] = " " + df["Category"].str.upper()
    idx = pick(0.10)                                                        # second date format
    df.loc[idx, "Order Date"] = pd.to_datetime(df.loc[idx, "Order Date"]).dt.strftime("%d-%b-%Y")
    idx = pick(0.05)                                                        # currency formatting
    df.loc[idx, "Sales"] = df.loc[idx, "Sales"].map(lambda v: f"₹{float(v):,.2f}")
    df.loc[pick(0.02), "Sales"] = np.nan                                    # missing values
    df.loc[pick(0.02), "Quantity"] = np.nan
    df.loc[pick(0.03), "Profit"] = np.nan
    df.loc[pick(0.01), "Region"] = np.nan
    df.loc[pick(0.005), "Order Date"] = np.nan
    df.loc[pick(0.005), "Order Date"] = "not a date"
    df.loc[pick(0.005), "Quantity"] = "-1"                                  # invalid values

    dup_exact = df.sample(frac=0.02, random_state=1)                         # duplicate rows
    dup_id = df.sample(frac=0.01, random_state=2).assign(Profit="0")        # same ID, edited row
    df = pd.concat([df, dup_exact, dup_id]).sample(frac=1, random_state=3)
    return df.reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2000)
    ap.add_argument("--month", default="2026-09", help="YYYY-MM")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/incoming/sales_2026_09.csv")
    a = ap.parse_args()
    generate(a.rows, a.month, a.seed).to_csv(a.out, index=False)
    print(f"Wrote {a.out}")
