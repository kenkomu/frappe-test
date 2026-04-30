import frappe
from frappe.tests import IntegrationTestCase


class TestItem(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Item", {"item_code": ["like", "_TEST-%"]})

	def tearDown(self):
		frappe.db.delete("Item", {"item_code": ["like", "_TEST-%"]})

	def make_item(self, item_code="_TEST-LAPTOP-001", item_name="Test Laptop", **kwargs):
		doc = frappe.get_doc({
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_name,
			"uom": "Nos",
			**kwargs,
		})
		doc.insert()
		return doc

	def test_item_creates_successfully(self):
		item = self.make_item()
		self.assertEqual(item.item_code, "_TEST-LAPTOP-001")
		self.assertEqual(item.item_name, "Test Laptop")
		self.assertEqual(item.uom, "Nos")
		self.assertEqual(item.is_active, 1)

	def test_item_code_is_uppercased(self):
		item = self.make_item(item_code="_test-lower-001", item_name="Lower Case Test")
		self.assertEqual(item.item_code, "_TEST-LOWER-001")

	def test_item_code_whitespace_is_stripped(self):
		item = self.make_item(item_code="  _TEST-SPACE-001  ", item_name="Space Test")
		self.assertEqual(item.item_code, "_TEST-SPACE-001")

	def test_duplicate_item_code_raises_error(self):
		self.make_item(item_code="_TEST-DUP-001", item_name="Original")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_item(item_code="_TEST-DUP-001", item_name="Duplicate")

	def test_item_code_is_required(self):
		# autoname raises ValidationError (not MandatoryError) when naming field is empty
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "Item",
				"item_name": "No Code Item",
				"uom": "Nos",
			}).insert()

	def test_item_name_is_required(self):
		with self.assertRaises((frappe.MandatoryError, frappe.ValidationError)):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "_TEST-NONAME-001",
				"uom": "Nos",
			}).insert()

	def test_uom_is_required(self):
		# explicitly clear the default so the mandatory check fires
		with self.assertRaises((frappe.MandatoryError, frappe.ValidationError)):
			doc = frappe.get_doc({
				"doctype": "Item",
				"item_code": "_TEST-NOUOM-001",
				"item_name": "No UOM Item",
			})
			doc.uom = ""
			doc.insert()

	def test_optional_fields_save_correctly(self):
		item = self.make_item(
			item_code="_TEST-FULL-001",
			item_name="Full Item",
			item_group="Laptops",
			description="A complete test item with all fields",
		)
		self.assertEqual(item.item_group, "Laptops")
		self.assertEqual(item.description, "A complete test item with all fields")
