"""
Shared test fixture helpers for the X Electronics WMS test suite.
Import from here instead of defining make_item / make_warehouse locally.
"""
import frappe


def make_item(item_code: str, item_name: str | None = None) -> None:
	if frappe.db.exists("Item", item_code):
		return
	frappe.get_doc({
		"doctype": "Item",
		"item_code": item_code,
		"item_name": item_name or item_code,
		"uom": "Nos",
	}).insert(ignore_permissions=True)


def make_warehouse(name: str, is_group: int = 0, parent: str | None = None) -> str:
	if not frappe.db.exists("Warehouse", name):
		frappe.get_doc({
			"doctype": "Warehouse",
			"warehouse_name": name,
			"is_group": is_group,
			"parent_warehouse": parent,
		}).insert(ignore_permissions=True)
	return name
