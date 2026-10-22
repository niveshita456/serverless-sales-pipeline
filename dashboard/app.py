"""Live sales dashboard (Streamlit). Reads directly from the Postgres warehouse.

Local:  DATABASE_URL=... streamlit run dashboard/app.py
Cloud:  Streamlit Community Cloud, with DATABASE_URL set in the app's Secrets.
"""
import os
import re

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

st.set_page_config(page_title="Sales Dashboard", page_icon="📊", layout="wide")


def database_url() -> str:
    try:
        url = st.secrets["DATABASE_URL"]
    except Exception:
        url = os.environ.get("DATABASE_URL", "")
    # Supabase gives "postgres://..."; pin the psycopg2 driver explicitly
    url = re.sub(r"^postgres(ql)?://", "postgresql+psycopg2://", url)
    return url


@st.cache_resource
def get_engine():
    return create_engine(database_url(), pool_pre_ping=True)


@st.cache_data(ttl=300)  # refresh from the database every 5 minutes
def load_sales() -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM sales_clean", get_engine(), parse_dates=["order_date", "order_month"])
    for c in ["unit_price", "sales", "profit", "profit_margin"]:
        df[c] = df[c].astype(float)
    return df


@st.cache_data(ttl=300)
def load_runs() -> pd.DataFrame:
    return pd.read_sql(
        "SELECT source_file, loaded_at, rows_in, rows_out, rows_upserted FROM pipeline_runs "
        "ORDER BY loaded_at DESC LIMIT 20",
        get_engine(),
    )


if not database_url():
    st.error("DATABASE_URL is not configured.")
    st.stop()

try:
    sales = load_sales()
    
except Exception as e:
       st.error(f"Could not reach the database ({type(e).__name__}).")
       st.code(re.sub(r"://[^@\s]*@", "://***@", str(e))[:1000])
       st.stop()

if sales.empty:
    st.info("No data yet. Push a CSV to data/incoming/ to run the pipeline.")
    st.stop()

# ---------- Sidebar filters ----------
st.sidebar.header("Filters")
regions = st.sidebar.multiselect("Region", sorted(sales["region"].unique()), default=sorted(sales["region"].unique()))
categories = st.sidebar.multiselect("Category", sorted(sales["category"].unique()),
                                    default=sorted(sales["category"].unique()))
min_d, max_d = sales["order_date"].min().date(), sales["order_date"].max().date()
dates = st.sidebar.date_input("Date range", (min_d, max_d), min_value=min_d, max_value=max_d)
if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()

start, end = (dates if isinstance(dates, tuple) and len(dates) == 2 else (min_d, max_d))
f = sales[
    sales["region"].isin(regions)
    & sales["category"].isin(categories)
    & sales["order_date"].dt.date.between(start, end)
]

# ---------- KPIs ----------
st.title("📊 Sales Performance")
st.caption(f"Data from {len(sales):,} orders · last loaded {pd.to_datetime(sales['ingested_at']).max():%d %b %Y, %H:%M} UTC")

total_sales, total_profit = f["sales"].sum(), f["profit"].sum()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total sales", f"₹{total_sales / 1e7:,.2f} Cr")
k2.metric("Total profit", f"₹{total_profit / 1e7:,.2f} Cr")
k3.metric("Profit margin", f"{(total_profit / total_sales * 100) if total_sales else 0:.1f}%")
k4.metric("Orders", f"{len(f):,}")

if f.empty:
    st.warning("No orders match these filters.")
    st.stop()

# ---------- Charts ----------
left, right = st.columns(2)
with left:
    st.subheader("Monthly sales and profit")
    monthly = f.groupby("order_month")[["sales", "profit"]].sum()
    monthly.index = monthly.index.strftime("%b %Y")
    st.bar_chart(monthly, stack=False)
with right:
    st.subheader("Sales by region")
    st.bar_chart(f.groupby("region")["sales"].sum().sort_values(ascending=False))

st.subheader("Sub-category performance")
sub = (f.groupby(["category", "sub_category"])
         .agg(orders=("order_id", "count"), sales=("sales", "sum"), profit=("profit", "sum"))
         .reset_index())
sub["margin_%"] = (sub["profit"] / sub["sales"] * 100).round(1)
sub = sub.sort_values("margin_%")
loss = sub[sub["profit"] < 0]
if not loss.empty:
    st.warning("Loss-making sub-categories: " + ", ".join(loss["sub_category"]))
st.dataframe(
    sub.style.format({"sales": "₹{:,.0f}", "profit": "₹{:,.0f}", "margin_%": "{:.1f}%"}),
    width="stretch", hide_index=True,
)

with st.expander("Pipeline runs (data quality)"):
    runs = load_runs()
    runs["rows_dropped"] = runs["rows_in"] - runs["rows_out"]
    st.dataframe(runs, width="stretch", hide_index=True)
    st.caption(f"{int(f['profit_imputed'].sum())} orders in this view have estimated profit (missing in source).")
