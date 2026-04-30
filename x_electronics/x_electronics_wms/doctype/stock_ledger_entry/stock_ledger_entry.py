import frappe
from frappe import _
from frappe.model.document import Document


class StockLedgerEntry(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_qty: DF.Float
		is_cancelled: DF.Check
		item: DF.Link
		posting_date: DF.Date
		posting_time: DF.Time
		stock_value_difference: DF.Currency
		valuation_rate: DF.Currency
		voucher_no: DF.DynamicLink
		voucher_type: DF.Data | None
		warehouse: DF.Link
	# end: auto-generated types

	def before_insert(self):
		self._validate_warehouse_is_not_group()
		self._validate_item_is_active()
		self.stock_value_difference = self.actual_qty * self.valuation_rate

	def _validate_warehouse_is_not_group(self):
		is_group = frappe.db.get_value("Warehouse", self.warehouse, "is_group")
		if is_group:
			frappe.throw(
				_("Cannot post stock entry to group Warehouse {0}. Select a leaf warehouse.").format(
					self.warehouse
				)
			)

	def _validate_item_is_active(self):
		is_active = frappe.db.get_value("Item", self.item, "is_active")
		if not is_active:
			frappe.throw(_("Item {0} is inactive and cannot be transacted.").format(self.item))
