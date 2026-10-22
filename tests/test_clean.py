import pandas as pd
import pytest

from src.clean import clean_sales


def raw(**overrides):
    row = {
        "Order ID": "ord-1", "Order Date": "2026-09-05", "Region": " north ",
        "Category": "TECHNOLOGY", "Sub-Category": "phones", "Quantity": "2",
        "Unit Price": "1000", "Sales": "₹2,000.00", "Profit": "240",
    }
    row.update(overrides)
    return row


def test_types_and_text_normalised():
    df, _ = clean_sales(pd.DataFrame([raw()]))
    r = df.iloc[0]
    assert r["order_id"] == "ORD-1"
    assert r["region"] == "North" and r["category"] == "Technology"
    assert r["sales"] == 2000.0 and r["quantity"] == 2
    assert str(r["order_month"].date()) == "2026-09-01"
    assert r["profit_margin"] == pytest.approx(0.12)


def test_mixed_date_formats():
    df, _ = clean_sales(pd.DataFrame([raw(), raw(**{"Order ID": "ord-2", "Order Date": "07-Sep-2026"})]))
    assert sorted(df["order_date"].dt.day) == [5, 7]


def test_duplicates_removed():
    df, rep = clean_sales(pd.DataFrame([raw(), raw(), raw(Profit="0")]))
    assert len(df) == 1
    assert rep["exact_duplicates_removed"] == 1
    assert rep["duplicate_order_ids_removed"] == 1


def test_unrecoverable_and_invalid_rows_dropped():
    rows = [
        raw(**{"Order ID": "a", "Order Date": "not a date"}),
        raw(**{"Order ID": "b", "Quantity": "-1"}),
        raw(**{"Order ID": "c", "Sales": None, "Unit Price": None}),
        raw(**{"Order ID": "d"}),
    ]
    df, rep = clean_sales(pd.DataFrame(rows))
    assert df["order_id"].tolist() == ["D"]
    assert rep["missing_id_or_date_dropped"] == 1
    assert rep["invalid_numeric_dropped"] == 2


def test_missing_values_derived_or_imputed():
    rows = [
        raw(**{"Order ID": "a", "Sales": None}),            # sales = qty x price
        raw(**{"Order ID": "b", "Quantity": None}),         # qty = sales / price
        raw(**{"Order ID": "c", "Profit": None}),           # profit from category margin
        raw(**{"Order ID": "d", "Region": None}),           # -> Unknown
    ]
    df, rep = clean_sales(pd.DataFrame(rows))
    df = df.set_index("order_id")
    assert rep["profit_imputed"] == 1
    assert df.loc["A", "sales"] == 2000.0
    assert df.loc["B", "quantity"] == 2
    assert df.loc["C", "profit_imputed"] and df.loc["C", "profit"] == pytest.approx(240.0)
    assert df.loc["D", "region"] == "Unknown"


def test_missing_column_raises():
    with pytest.raises(ValueError, match="sales"):
        clean_sales(pd.DataFrame([raw()]).drop(columns=["Sales"]))
