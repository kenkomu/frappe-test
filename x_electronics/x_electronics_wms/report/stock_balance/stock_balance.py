import frappe
from frappe import _
from frappe.utils import today


def execute(filters=None):
	filters = filters or {}
	if not filters.get("as_of_date"):
		filters["as_of_date"] = today()
	return get_columns(), get_data(filters)


# ── columns ────────────────────────────────────────────────────────────────────

def get_columns():
	return [
		{
			"label": _("Item"),
			"fieldname": "item",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 180,
		},
		{
			"label": _("Balance Qty"),
			"fieldname": "balance_qty",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Valuation Rate"),
			"fieldname": "valuation_rate",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Stock Value"),
			"fieldname": "stock_value",
			"fieldtype": "Currency",
			"width": 130,
		},
	]


# ── data ───────────────────────────────────────────────────────────────────────

def get_data(filters):
	warehouse_condition, values = _build_warehouse_condition(filters)
	item_condition = ""
	if filters.get("item"):
		item_condition = "AND sle.item = %(item)s"
		values["item"] = filters["item"]

	values["as_of_date"] = filters["as_of_date"]

	# Leaf-level balances as of the requested date.
	# valuation_rate = total_stock_value / qty — the moving average for that
	# warehouse at the cut-off date, computed purely from raw ledger rows.
	leaf_rows = frappe.db.sql(
		f"""
		SELECT
			sle.item,
			i.item_name,
			sle.warehouse,
			SUM(sle.actual_qty)                                              AS balance_qty,
			SUM(sle.stock_value_difference) /
				NULLIF(SUM(sle.actual_qty), 0)                               AS valuation_rate,
			SUM(sle.stock_value_difference)                                  AS stock_value
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` i ON i.name = sle.item
		WHERE sle.posting_date <= %(as_of_date)s
		  {item_condition}
		  {warehouse_condition}
		GROUP BY sle.item, sle.warehouse
		HAVING SUM(sle.actual_qty) != 0
		ORDER BY sle.item, sle.warehouse
		""",
		values,
		as_dict=True,
	)

	# When the filter targets a group warehouse, append one consolidated
	# summary row per item showing the total across all children.
	if _is_group_warehouse(filters.get("warehouse")):
		return _append_group_totals(leaf_rows, filters["warehouse"])

	return leaf_rows


# ── tree consolidation ─────────────────────────────────────────────────────────

def _build_warehouse_condition(filters):
	"""
	Return a WHERE clause fragment and its bind values for the warehouse filter.

	- No filter  → no restriction (all warehouses).
	- Leaf node  → exact match.
	- Group node → all descendants using the NestedSet lft/rgt range,
	               a single range scan with no recursion.
	"""
	warehouse = filters.get("warehouse")
	if not warehouse:
		return "", {}

	if not _is_group_warehouse(warehouse):
		return "AND sle.warehouse = %(warehouse)s", {"warehouse": warehouse}

	# Group warehouse: resolve lft/rgt once, then use a range sub-select.
	lft, rgt = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"])
	return (
		"""
		AND sle.warehouse IN (
			SELECT name FROM `tabWarehouse`
			WHERE lft >= %(lft)s AND rgt <= %(rgt)s
			  AND is_group = 0
		)
		""",
		{"lft": lft, "rgt": rgt},
	)


def _is_group_warehouse(warehouse):
	if not warehouse:
		return False
	return bool(frappe.db.get_value("Warehouse", warehouse, "is_group"))


def _append_group_totals(leaf_rows, group_warehouse):
	"""
	Group the leaf rows by item and append a consolidated summary row per item.
	The summary row uses the group warehouse name as the warehouse label.
	"""
	from collections import defaultdict

	totals = defaultdict(lambda: {"balance_qty": 0.0, "stock_value": 0.0, "item_name": ""})
	for row in leaf_rows:
		t = totals[row.item]
		t["balance_qty"] += row.balance_qty
		t["stock_value"] += row.stock_value
		t["item_name"]    = row.item_name

	summary_rows = []
	for item, t in sorted(totals.items()):
		qty = t["balance_qty"]
		val = t["stock_value"]
		summary_rows.append(
			frappe._dict(
				item=item,
				item_name=t["item_name"],
				warehouse=group_warehouse,
				balance_qty=qty,
				valuation_rate=val / qty if qty else 0.0,
				stock_value=val,
				# visual marker so the UI can bold/indent consolidated rows
				is_group_total=1,
			)
		)

	return list(leaf_rows) + summary_rows
