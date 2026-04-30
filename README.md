# X Electronics WMS

A production-ready Warehouse Management System built on the [Frappe Framework](https://frappeframework.com) for X Electronics.

Built as part of the Navari Limited Software Engineer technical exercise.

---

## What it does

Tracks stock movement across a hierarchical warehouse structure with full audit trail and moving average valuation.

| Feature | Detail |
|---|---|
| **Items** | Product master with code normalization |
| **Warehouses** | Tree (NestedSet) structure — group and leaf nodes |
| **Stock Entries** | Receipt, Consume, Transfer with submit/cancel lifecycle |
| **Stock Ledger** | Stateless, immutable ledger — cancellation posts reversing rows, never edits existing ones |
| **Moving Average Valuation** | Computed via a single SQL aggregation — no stored running totals |
| **Stock Ledger Report** | Per-movement running balance using SQL window functions |
| **Stock Balance Report** | Point-in-time balance with warehouse tree consolidation |
| **Test Coverage** | 84 integration tests across all DocTypes and reports |

---

## Tech stack

| Layer | Choice |
|---|---|
| Framework | Frappe v17 (Python + JavaScript) |
| Backend logic | Python — controllers, valuation engine, reports, tests |
| Frontend | JavaScript — dynamic form behaviour, live field calculation |
| Database | MariaDB — via Frappe ORM and raw SQL (window functions for reports) |

---

## Installation

### Prerequisites

- Python 3.10+
- Node.js 18+
- MariaDB 10.6+
- [Frappe Bench](https://github.com/frappe/bench)

### Steps

```bash
# 1. Get the app into your bench
cd /path/to/your/bench
bench get-app https://github.com/kenkomu/x-electronics-wms --branch main

# 2. Create a site (skip if you already have one)
bench new-site x-electronics.localhost --admin-password admin123

# 3. Install the app
bench --site x-electronics.localhost install-app x_electronics

# 4. Enable developer mode
bench --site x-electronics.localhost set-config developer_mode 1

# 5. Run migrations
bench --site x-electronics.localhost migrate

# 6. Start the server
bench start
```

Open `http://x-electronics.localhost:8000` and log in with `Administrator` / `admin123`.

---

## Running tests

```bash
# Enable tests on the site (one-time)
bench --site x-electronics.localhost set-config allow_tests true

# Run the full suite (84 tests)
bench --site x-electronics.localhost run-tests --app x_electronics

# Run a single module
bench --site x-electronics.localhost run-tests \
  --module x_electronics.x_electronics_wms.doctype.stock_entry.test_stock_entry
```

---

## Architecture & design decisions

### Stateless Stock Ledger Entry

ERPNext's SLE is stateful — it stores `qty_after_transaction` as a running total and must repost the entire chain when a backdated entry is added. This creates fragile cascades.

This system takes the opposite approach:

> **The SLE is an immutable ledger row.** Current balance and valuation rate are always computed from raw SLE data via SQL. Cancellation posts new reversing rows — existing rows are never modified or deleted.

Proof: `test_cancel_receipt_does_not_delete_original_sles` asserts that after cancellation, both the original `+10` row and the reversing `-10` row exist with `is_cancelled` flags — the original is untouched.

### Moving average valuation — one SQL query

When a Receipt is posted, the new weighted average rate is computed as:

```
new_rate = (current_stock_value + incoming_qty × incoming_rate)
         / (current_qty + incoming_qty)
```

Where `current_stock_value` and `current_qty` come from:

```sql
SELECT
    COALESCE(SUM(actual_qty), 0)             AS qty,
    COALESCE(SUM(stock_value_difference), 0) AS stock_value
FROM `tabStock Ledger Entry`
WHERE item = %(item)s AND warehouse = %(warehouse)s
```

One query, pure arithmetic — no loops, no stateful chain.

The `valuation_rate` stored in each SLE is the **incoming purchase rate** (for receipts) or the **current moving average** (for consumes/transfers). This keeps `stock_value_difference = actual_qty × valuation_rate` consistent for all entry types, and means `get_valuation_rate = SUM(stock_value_difference) / SUM(actual_qty)` always returns the correct moving average.

### Stock Ledger report — window functions

Running balance is computed in a single SQL pass using window functions — no Python accumulation:

```sql
SUM(sle.actual_qty) OVER (
    PARTITION BY sle.item, sle.warehouse
    ORDER BY sle.posting_date, sle.posting_time, sle.creation
    ROWS UNBOUNDED PRECEDING
) AS balance_qty
```

`PARTITION BY item, warehouse` ensures each item-warehouse pair has its own independent running total. `creation` as the tiebreaker guarantees a stable order for same-second entries.

### Stock Balance report — tree consolidation without recursion

When a group warehouse is selected, all leaf descendants are resolved using the NestedSet `lft`/`rgt` range — one index scan, no recursive CTEs, no application-side tree walking:

```sql
AND sle.warehouse IN (
    SELECT name FROM `tabWarehouse`
    WHERE lft >= %(lft)s AND rgt <= %(rgt)s
      AND is_group = 0
)
```

---

## Project structure

```
x_electronics/
└── x_electronics_wms/          ← module
    ├── utils.py                 ← valuation engine (shared by DocTypes + reports)
    ├── doctype/
    │   ├── item/
    │   ├── warehouse/
    │   ├── stock_ledger_entry/
    │   ├── stock_entry/
    │   └── stock_entry_detail/
    └── report/
        ├── stock_ledger/
        └── stock_balance/
```

---

## License

MIT
