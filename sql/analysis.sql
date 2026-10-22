-- ============================================================
-- Analysis queries (PostgreSQL). Run in the Supabase SQL Editor.
-- The tables sales_clean and pipeline_runs are created
-- automatically by the pipeline on its first run.
-- ============================================================

-- 01. Sales and profit by region
SELECT
  region,
  COUNT(*)                                            AS orders,
  ROUND(SUM(sales), 0)                                AS total_sales,
  ROUND(SUM(profit), 0)                               AS total_profit,
  ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 1) AS margin_pct
FROM sales_clean
GROUP BY region
ORDER BY total_sales DESC;


-- 02. Category / sub-category performance; flags loss-makers
SELECT
  category,
  sub_category,
  ROUND(SUM(sales), 0)                                AS total_sales,
  ROUND(SUM(profit), 0)                               AS total_profit,
  ROUND(SUM(profit) / NULLIF(SUM(sales), 0) * 100, 1) AS margin_pct,
  CASE WHEN SUM(profit) < 0 THEN 'LOSS-MAKING' ELSE 'OK' END AS status
FROM sales_clean
GROUP BY category, sub_category
ORDER BY margin_pct;


-- 03. Monthly trend with month-over-month growth (window function)
WITH monthly AS (
  SELECT order_month, SUM(sales) AS sales, SUM(profit) AS profit
  FROM sales_clean
  GROUP BY order_month
)
SELECT
  order_month,
  ROUND(sales, 0)  AS sales,
  ROUND(profit, 0) AS profit,
  ROUND((sales - LAG(sales) OVER (ORDER BY order_month))
        / NULLIF(LAG(sales) OVER (ORDER BY order_month), 0) * 100, 1) AS mom_growth_pct
FROM monthly
ORDER BY order_month;


-- 04. Top 3 sub-categories per region by profit (ranking within groups)
SELECT region, sub_category, total_profit, rank_in_region
FROM (
  SELECT region, sub_category,
         ROUND(SUM(profit), 0) AS total_profit,
         RANK() OVER (PARTITION BY region ORDER BY SUM(profit) DESC) AS rank_in_region
  FROM sales_clean
  GROUP BY region, sub_category
) ranked
WHERE rank_in_region <= 3
ORDER BY region, rank_in_region;


-- 05. Data quality per pipeline run (reads the JSON report)
SELECT
  source_file,
  loaded_at,
  rows_in,
  rows_out,
  (report ->> 'exact_duplicates_removed')::int
    + (report ->> 'duplicate_order_ids_removed')::int AS duplicates_removed,
  (report ->> 'profit_imputed')::int                  AS profit_imputed,
  ROUND(100.0 * (rows_in - rows_out) / NULLIF(rows_in, 0), 1) AS pct_rows_dropped
FROM pipeline_runs
ORDER BY loaded_at DESC;
