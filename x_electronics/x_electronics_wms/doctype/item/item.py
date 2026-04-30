import frappe
from frappe import _
from frappe.model.document import Document


class Item(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		is_active: DF.Check
		item_code: DF.Data
		item_group: DF.Data | None
		item_name: DF.Data
		uom: DF.Data
	# end: auto-generated types

	def autoname(self):
		if not self.item_code:
			frappe.throw(_("Item Code is required"), frappe.ValidationError)
		self.item_code = self.item_code.strip().upper()
		self.name = self.item_code

	def validate(self):
		if self.item_name:
			self.item_name = self.item_name.strip()
		if self.item_group:
			self.item_group = self.item_group.strip()
