import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 100,
		},
		{
			"label": _("Time"),
			"fieldname": "posting_time",
			"fieldtype": "Time",
			"width": 80,
		},
		{
			"label": _("Voucher"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
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
			"width": 180,
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 150,
		},
		{
			"label": _("In Qty"),
			"fieldname": "qty_in",
			"fieldtype": "Float",
			"width": 90,
		},
		{
			"label": _("Out Qty"),
			"fieldname": "qty_out",
			"fieldtype": "Float",
			"width": 90,
		},
		{
			"label": _("Balance Qty"),
			"fieldname": "balance_qty",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Valuation Rate"),
			"fieldname": "valuation_rate",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Stock Value"),
			"fieldname": "stock_value",
			"fieldtype": "Currency",
			"width": 120,
		},
	]


def get_data(filters):
	conditions, values = _build_conditions(filters)

	# Window functions compute the running balance and cumulative stock value
	# per item+warehouse in chronological order.  No stored running totals —
	# every number here is derived from the raw ledger rows.
	return frappe.db.sql(
		f"""
		SELECT
			sle.posting_date,
			sle.posting_time,
			sle.voucher_type,
			sle.voucher_no,
			sle.item,
			i.item_name,
			sle.warehouse,
			CASE WHEN sle.actual_qty > 0
				THEN  sle.actual_qty ELSE 0 END                          AS qty_in,
			CASE WHEN sle.actual_qty < 0
				THEN ABS(sle.actual_qty) ELSE 0 END                      AS qty_out,
			SUM(sle.actual_qty) OVER (
				PARTITION BY sle.item, sle.warehouse
				ORDER BY sle.posting_date, sle.posting_time, sle.creation
				ROWS UNBOUNDED PRECEDING
			)                                                            AS balance_qty,
			sle.valuation_rate,
			SUM(sle.stock_value_difference) OVER (
				PARTITION BY sle.item, sle.warehouse
				ORDER BY sle.posting_date, sle.posting_time, sle.creation
				ROWS UNBOUNDED PRECEDING
			)                                                            AS stock_value
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` i ON i.name = sle.item
		WHERE {conditions}
		ORDER BY sle.item, sle.warehouse, sle.posting_date, sle.posting_time, sle.creation
		""",
		values,
		as_dict=True,
	)


def _build_conditions(filters):
	conditions = ["1=1"]
	values = {}

	if filters.get("from_date"):
		conditions.append("sle.posting_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("sle.posting_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	if filters.get("item"):
		conditions.append("sle.item = %(item)s")
		values["item"] = filters["item"]

	if filters.get("warehouse"):
		conditions.append("sle.warehouse = %(warehouse)s")
		values["warehouse"] = filters["warehouse"]

	return " AND ".join(conditions), values
