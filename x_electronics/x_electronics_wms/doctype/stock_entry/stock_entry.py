import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowtime, today

from x_electronics.x_electronics_wms.utils import (
	get_moving_avg_valuation,
	get_stock_balance,
	get_valuation_rate,
	post_stock_ledger_entry,
)


class StockEntry(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from x_electronics.x_electronics_wms.doctype.stock_entry_detail.stock_entry_detail import (
			StockEntryDetail,
		)

		from_warehouse: DF.Link | None
		items: DF.Table[StockEntryDetail]
		posting_date: DF.Date
		posting_time: DF.Time | None
		remarks: DF.SmallText | None
		stock_entry_type: DF.Literal["Receipt", "Consume", "Transfer"]
		to_warehouse: DF.Link | None
		total_amount: DF.Currency
	# end: auto-generated types

	def validate(self):
		self._set_posting_time()
		self._validate_warehouses()
		self._validate_items()
		self._calculate_totals()

	def on_submit(self):
		self._make_stock_ledger_entries()

	def on_cancel(self):
		self._make_reverse_stock_ledger_entries()

	# ── private helpers ────────────────────────────────────────────────────────

	def _set_posting_time(self):
		if not self.posting_time:
			self.posting_time = nowtime()
		if not self.posting_date:
			self.posting_date = today()

	def _validate_warehouses(self):
		t = self.stock_entry_type
		if t == "Receipt":
			if not self.to_warehouse and not any(r.to_warehouse for r in self.items):
				frappe.throw(_("To Warehouse is required for Receipt."))
		elif t == "Consume":
			if not self.from_warehouse and not any(r.from_warehouse for r in self.items):
				frappe.throw(_("From Warehouse is required for Consume."))
		elif t == "Transfer":
			if not self.from_warehouse and not any(r.from_warehouse for r in self.items):
				frappe.throw(_("From Warehouse is required for Transfer."))
			if not self.to_warehouse and not any(r.to_warehouse for r in self.items):
				frappe.throw(_("To Warehouse is required for Transfer."))
			src = self.from_warehouse
			dst = self.to_warehouse
			if src and dst and src == dst:
				frappe.throw(_("From Warehouse and To Warehouse cannot be the same."))

	def _validate_items(self):
		if not self.items:
			frappe.throw(_("At least one item is required."))

		for row in self.items:
			if row.qty <= 0:
				frappe.throw(_("Row {0}: Qty must be greater than zero.").format(row.idx))

			if self.stock_entry_type in ("Consume", "Transfer"):
				src = row.from_warehouse or self.from_warehouse
				available = get_stock_balance(row.item, src)
				if available < row.qty:
					frappe.throw(
						_(
							"Row {0}: Insufficient stock for {1} in {2}. "
							"Available: {3}, Required: {4}."
						).format(row.idx, row.item, src, available, row.qty)
					)

	def _calculate_totals(self):
		for row in self.items:
			row.amount = row.qty * (row.rate or 0)
		self.total_amount = sum(row.amount for row in self.items)

	def _effective_warehouses(self, row):
		"""Return (from_wh, to_wh) for this row, falling back to header values."""
		return (
			row.from_warehouse or self.from_warehouse,
			row.to_warehouse or self.to_warehouse,
		)

	def _make_stock_ledger_entries(self):
		t = self.stock_entry_type
		for row in self.items:
			from_wh, to_wh = self._effective_warehouses(row)

			if t == "Receipt":
				rate = get_moving_avg_valuation(row.item, to_wh, row.qty, row.rate or 0)
				self._post(row.item, to_wh, row.qty, row.rate or rate)

			elif t == "Consume":
				rate = get_valuation_rate(row.item, from_wh)
				self._post(row.item, from_wh, -row.qty, rate)

			elif t == "Transfer":
				rate = get_valuation_rate(row.item, from_wh)
				self._post(row.item, from_wh, -row.qty, rate)
				self._post(row.item, to_wh, row.qty, rate)

	def _make_reverse_stock_ledger_entries(self):
		"""
		Post mirror-image SLEs to reverse a cancelled entry.
		Original SLE rows are never touched — reversal is always new rows.
		"""
		t = self.stock_entry_type
		for row in self.items:
			from_wh, to_wh = self._effective_warehouses(row)
			rate = get_valuation_rate(row.item, to_wh if t == "Receipt" else from_wh)

			if t == "Receipt":
				self._post(row.item, to_wh, -row.qty, rate, is_cancelled=1)

			elif t == "Consume":
				self._post(row.item, from_wh, row.qty, rate, is_cancelled=1)

			elif t == "Transfer":
				self._post(row.item, from_wh, row.qty, rate, is_cancelled=1)
				self._post(row.item, to_wh, -row.qty, rate, is_cancelled=1)

	def _post(self, item, warehouse, qty, rate, is_cancelled=0):
		post_stock_ledger_entry(
			item=item,
			warehouse=warehouse,
			actual_qty=qty,
			valuation_rate=rate,
			posting_date=self.posting_date,
			posting_time=self.posting_time,
			voucher_type="Stock Entry",
			voucher_no=self.name,
			is_cancelled=is_cancelled,
		)
