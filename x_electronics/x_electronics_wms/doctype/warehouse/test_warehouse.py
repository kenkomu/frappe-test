import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.nestedset import NestedSetChildExistsError


class TestWarehouse(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Warehouse", {"warehouse_name": ["like", "_Test%"]})

	def tearDown(self):
		frappe.db.delete("Warehouse", {"warehouse_name": ["like", "_Test%"]})

	def make_warehouse(self, name, is_group=0, parent=None):
		doc = frappe.get_doc({
			"doctype": "Warehouse",
			"warehouse_name": name,
			"is_group": is_group,
			"parent_warehouse": parent,
		})
		doc.insert()
		return doc

	# ── creation ──────────────────────────────────────────────────────────────

	def test_create_root_group_warehouse(self):
		wh = self.make_warehouse("_Test Main WH", is_group=1)
		self.assertEqual(wh.warehouse_name, "_Test Main WH")
		self.assertEqual(wh.is_group, 1)
		self.assertIsNone(wh.parent_warehouse)

	def test_create_child_warehouse(self):
		parent = self.make_warehouse("_Test Parent WH", is_group=1)
		child = self.make_warehouse("_Test Child WH", is_group=0, parent=parent.name)
		self.assertEqual(child.parent_warehouse, parent.name)

	def test_duplicate_warehouse_name_raises_error(self):
		# both as is_group=1 (no parent needed) so validate() passes and the
		# DB unique constraint is what fires
		self.make_warehouse("_Test Dup WH", is_group=1)
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_warehouse("_Test Dup WH", is_group=1)

	# ── tree structure ─────────────────────────────────────────────────────────

	def test_lft_rgt_set_after_insert(self):
		wh = self.make_warehouse("_Test NSM WH", is_group=1)
		wh.reload()
		self.assertGreater(wh.lft, 0)
		self.assertGreater(wh.rgt, wh.lft)

	def test_parent_lft_rgt_wraps_child(self):
		parent = self.make_warehouse("_Test Tree Parent", is_group=1)
		child = self.make_warehouse("_Test Tree Child", is_group=0, parent=parent.name)
		parent.reload()
		child.reload()
		self.assertGreater(child.lft, parent.lft)
		self.assertLess(child.rgt, parent.rgt)

	def test_multiple_children_within_parent_bounds(self):
		parent = self.make_warehouse("_Test Multi Parent", is_group=1)
		c1 = self.make_warehouse("_Test Multi Child 1", is_group=0, parent=parent.name)
		c2 = self.make_warehouse("_Test Multi Child 2", is_group=0, parent=parent.name)
		parent.reload()
		c1.reload()
		c2.reload()
		self.assertGreater(c1.lft, parent.lft)
		self.assertGreater(c2.lft, parent.lft)
		self.assertLess(c1.rgt, parent.rgt)
		self.assertLess(c2.rgt, parent.rgt)

	# ── validation ─────────────────────────────────────────────────────────────

	def test_leaf_warehouse_requires_parent(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_warehouse("_Test Orphan WH", is_group=0, parent=None)

	def test_cannot_delete_group_with_children(self):
		parent = self.make_warehouse("_Test Del Parent", is_group=1)
		self.make_warehouse("_Test Del Child", is_group=0, parent=parent.name)
		with self.assertRaises(NestedSetChildExistsError):
			frappe.delete_doc("Warehouse", parent.name)

	def test_can_delete_empty_group(self):
		wh = self.make_warehouse("_Test Empty Group", is_group=1)
		frappe.delete_doc("Warehouse", wh.name)
		self.assertFalse(frappe.db.exists("Warehouse", wh.name))

	def test_can_delete_leaf_with_no_stock(self):
		parent = self.make_warehouse("_Test Leaf Parent", is_group=1)
		leaf = self.make_warehouse("_Test Leaf No Stock", is_group=0, parent=parent.name)
		frappe.delete_doc("Warehouse", leaf.name)
		self.assertFalse(frappe.db.exists("Warehouse", leaf.name))
