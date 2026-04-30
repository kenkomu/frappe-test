import frappe
from frappe import _


def get_stock_position(item: str, warehouse: str) -> dict:
	"""
	Return the current qty and total stock value for an item-warehouse pair.
	Both are computed from raw SLE rows — nothing is stored as a running total.
	"""
	result = frappe.db.sql(
		"""
		SELECT
			COALESCE(SUM(actual_qty), 0)            AS qty,
			COALESCE(SUM(stock_value_difference), 0) AS stock_value
		FROM `tabStock Ledger Entry`
		WHERE item = %(item)s
		  AND warehouse = %(warehouse)s
		""",
		{"item": item, "warehouse": warehouse},
		as_dict=True,
	)
	return result[0]


def get_stock_balance(item: str, warehouse: str, posting_date: str | None = None) -> float:
	"""Return the qty on hand for item+warehouse, optionally as of a past date."""
	filters = {"item": item, "warehouse": warehouse}
	date_clause = ""
	if posting_date:
		date_clause = "AND posting_date <= %(posting_date)s"
		filters["posting_date"] = posting_date

	result = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(actual_qty), 0) AS qty
		FROM `tabStock Ledger Entry`
		WHERE item = %(item)s
		  AND warehouse = %(warehouse)s
		  {date_clause}
		""",
		filters,
		as_dict=True,
	)
	return result[0].qty


@frappe.whitelist()
def get_valuation_rate(item: str, warehouse: str) -> float:
	"""
	Return the current moving-average valuation rate for item+warehouse.
	Computed as total_stock_value / total_qty from all SLE rows.
	Returns 0.0 when there is no stock.
	"""
	pos = get_stock_position(item, warehouse)
	if not pos.qty:
		return 0.0
	return pos.stock_value / pos.qty


def get_moving_avg_valuation(
	item: str,
	warehouse: str,
	incoming_qty: float,
	incoming_rate: float,
) -> float:
	"""
	Compute the new moving-average valuation rate after a receipt.

	Formula:
	    new_rate = (current_stock_value + incoming_qty * incoming_rate)
	             / (current_qty + incoming_qty)

	This is a single SQL query followed by arithmetic — no loops, no iteration
	over historical rows.  When there is no prior stock the incoming rate is
	returned as-is.
	"""
	if incoming_qty <= 0:
		frappe.throw(_("Incoming qty must be greater than zero for valuation."))

	pos = get_stock_position(item, warehouse)
	new_total_qty = pos.qty + incoming_qty

	if new_total_qty == 0:
		return incoming_rate

	new_total_value = pos.stock_value + (incoming_qty * incoming_rate)
	return new_total_value / new_total_qty


def post_stock_ledger_entry(
	item: str,
	warehouse: str,
	actual_qty: float,
	valuation_rate: float,
	posting_date: str,
	posting_time: str,
	voucher_type: str = "",
	voucher_no: str = "",
	is_cancelled: int = 0,
) -> "StockLedgerEntry":
	"""
	Insert a single SLE row.  The only sanctioned way to create SLE records —
	Stock Entry (and its cancellation) calls this; nothing else should.
	"""
	from frappe.utils import nowtime

	sle = frappe.get_doc(
		{
			"doctype": "Stock Ledger Entry",
			"item": item,
			"warehouse": warehouse,
			"actual_qty": actual_qty,
			"valuation_rate": valuation_rate,
			"posting_date": posting_date,
			"posting_time": posting_time or nowtime(),
			"voucher_type": voucher_type,
			"voucher_no": voucher_no,
			"is_cancelled": is_cancelled,
		}
	)
	# ignore_links skips Dynamic Link validation for voucher_no when
	# voucher_type is empty or a non-DocType value (e.g. in tests)
	sle.insert(ignore_permissions=True, ignore_links=not voucher_type)
	return sle
