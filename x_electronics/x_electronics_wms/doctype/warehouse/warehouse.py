import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet, NestedSetChildExistsError


class Warehouse(NestedSet):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		is_group: DF.Check
		lft: DF.Int
		old_parent: DF.Link | None
		parent_warehouse: DF.Link | None
		rgt: DF.Int
		warehouse_name: DF.Data
	# end: auto-generated types

	nsm_parent_field = "parent_warehouse"

	def validate(self):
		if not self.is_group and not self.parent_warehouse:
			frappe.throw(_("A non-group Warehouse must have a Parent Warehouse."))

	def on_trash(self):
		self._validate_no_stock_ledger_entries()
		# let NestedSet handle child-existence check and tree rebalancing
		super().on_trash()

	def _validate_no_stock_ledger_entries(self):
		if not frappe.db.table_exists("Stock Ledger Entry"):
			return
		if frappe.db.exists("Stock Ledger Entry", {"warehouse": self.name}):
			frappe.throw(
				_("Cannot delete Warehouse {0} because it has stock transactions.").format(self.name)
			)
