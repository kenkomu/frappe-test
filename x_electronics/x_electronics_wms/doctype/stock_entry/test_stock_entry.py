import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today, nowtime

from x_electronics.x_electronics_wms.utils import get_stock_balance, get_valuation_rate


# ── shared fixtures ────────────────────────────────────────────────────────────

def make_item(item_code):
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc({
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"uom": "Nos",
		}).insert(ignore_permissions=True)


def make_warehouse(name, is_group=0, parent=None):
	if not frappe.db.exists("Warehouse", name):
		frappe.get_doc({
			"doctype": "Warehouse",
			"warehouse_name": name,
			"is_group": is_group,
			"parent_warehouse": parent,
		}).insert(ignore_permissions=True)


def setup_fixtures():
	make_item("_TEST-SE-LAPTOP")
	make_item("_TEST-SE-CABLE")
	make_warehouse("_Test SE Root", is_group=1)
	make_warehouse("_Test SE Store",   is_group=0, parent="_Test SE Root")
	make_warehouse("_Test SE Shelf A", is_group=0, parent="_Test SE Root")
	make_warehouse("_Test SE Shelf B", is_group=0, parent="_Test SE Root")


# ── test class ─────────────────────────────────────────────────────────────────

class TestStockEntry(IntegrationTestCase):

	def setUp(self):
		setup_fixtures()
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TEST-SE-%"]})
		frappe.db.delete("Stock Entry", {"remarks": "test"})

	def tearDown(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TEST-SE-%"]})

	# ── helpers ────────────────────────────────────────────────────────────────

	def _make_entry(self, entry_type, items, from_wh=None, to_wh=None, submit=True):
		doc = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": entry_type,
			"posting_date": today(),
			"posting_time": nowtime(),
			"from_warehouse": from_wh,
			"to_warehouse": to_wh,
			"remarks": "test",
			"items": items,
		})
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def _receipt(self, item, qty, rate, to_wh="_Test SE Store"):
		return self._make_entry(
			"Receipt",
			[{"item": item, "qty": qty, "rate": rate}],
			to_wh=to_wh,
		)

	def _consume(self, item, qty, from_wh="_Test SE Store"):
		return self._make_entry(
			"Consume",
			[{"item": item, "qty": qty}],
			from_wh=from_wh,
		)

	def _transfer(self, item, qty, from_wh="_Test SE Store", to_wh="_Test SE Shelf A"):
		return self._make_entry(
			"Transfer",
			[{"item": item, "qty": qty}],
			from_wh=from_wh,
			to_wh=to_wh,
		)

	# ── Receipt ────────────────────────────────────────────────────────────────

	def test_receipt_creates_positive_sle(self):
		self._receipt("_TEST-SE-LAPTOP", 10, 1000.0)
		sles = frappe.get_all("Stock Ledger Entry",
			filters={"item": "_TEST-SE-LAPTOP", "warehouse": "_Test SE Store"},
			fields=["actual_qty", "valuation_rate", "stock_value_difference"],
		)
		self.assertEqual(len(sles), 1)
		self.assertEqual(sles[0].actual_qty, 10)
		self.assertEqual(sles[0].stock_value_difference, 10000.0)

	def test_receipt_increases_stock_balance(self):
		self._receipt("_TEST-SE-LAPTOP", 10, 1000.0)
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 10)

	def test_receipt_moving_avg_across_two_receipts(self):
		self._receipt("_TEST-SE-LAPTOP", 10, 1000.0)  # value = 10 000
		self._receipt("_TEST-SE-LAPTOP", 10, 2000.0)  # value = 20 000
		# moving avg = 30 000 / 20 = 1 500
		self.assertAlmostEqual(get_valuation_rate("_TEST-SE-LAPTOP", "_Test SE Store"), 1500.0)

	def test_receipt_total_amount_computed(self):
		doc = self._receipt("_TEST-SE-LAPTOP", 5, 800.0)
		self.assertEqual(doc.total_amount, 4000.0)

	# ── Consume ────────────────────────────────────────────────────────────────

	def test_consume_creates_negative_sle(self):
		self._receipt("_TEST-SE-LAPTOP", 20, 500.0)
		self._consume("_TEST-SE-LAPTOP", 5)
		sles = frappe.get_all("Stock Ledger Entry",
			filters={"item": "_TEST-SE-LAPTOP", "warehouse": "_Test SE Store"},
			fields=["actual_qty"],
			order_by="creation asc",
		)
		self.assertEqual(sles[1].actual_qty, -5)

	def test_consume_reduces_stock_balance(self):
		self._receipt("_TEST-SE-LAPTOP", 20, 500.0)
		self._consume("_TEST-SE-LAPTOP", 7)
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 13)

	def test_consume_insufficient_stock_raises_error(self):
		self._receipt("_TEST-SE-LAPTOP", 5, 500.0)
		with self.assertRaises(frappe.ValidationError):
			self._consume("_TEST-SE-LAPTOP", 10)

	def test_consume_from_zero_stock_raises_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._consume("_TEST-SE-LAPTOP", 1)

	# ── Transfer ───────────────────────────────────────────────────────────────

	def test_transfer_creates_two_sles(self):
		self._receipt("_TEST-SE-CABLE", 30, 50.0)
		self._transfer("_TEST-SE-CABLE", 10)
		sle_store = get_stock_balance("_TEST-SE-CABLE", "_Test SE Store")
		sle_shelf = get_stock_balance("_TEST-SE-CABLE", "_Test SE Shelf A")
		self.assertEqual(sle_store, 20)
		self.assertEqual(sle_shelf, 10)

	def test_transfer_preserves_valuation_rate(self):
		self._receipt("_TEST-SE-CABLE", 20, 100.0)
		self._transfer("_TEST-SE-CABLE", 10)
		# rate in destination should match source rate
		rate_src = get_valuation_rate("_TEST-SE-CABLE", "_Test SE Store")
		rate_dst = get_valuation_rate("_TEST-SE-CABLE", "_Test SE Shelf A")
		self.assertAlmostEqual(rate_src, rate_dst)

	def test_transfer_same_warehouse_raises_error(self):
		self._receipt("_TEST-SE-CABLE", 10, 50.0)
		with self.assertRaises(frappe.ValidationError):
			self._transfer("_TEST-SE-CABLE", 5, from_wh="_Test SE Store", to_wh="_Test SE Store")

	def test_transfer_insufficient_stock_raises_error(self):
		self._receipt("_TEST-SE-CABLE", 5, 50.0)
		with self.assertRaises(frappe.ValidationError):
			self._transfer("_TEST-SE-CABLE", 10)

	# ── Cancellation ───────────────────────────────────────────────────────────

	def test_cancel_receipt_reverses_balance(self):
		entry = self._receipt("_TEST-SE-LAPTOP", 10, 1000.0)
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 10)
		entry.cancel()
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 0)

	def test_cancel_receipt_does_not_delete_original_sles(self):
		entry = self._receipt("_TEST-SE-LAPTOP", 10, 1000.0)
		entry.cancel()
		# both original (+10) and reversal (-10) rows should exist
		sles = frappe.get_all("Stock Ledger Entry",
			filters={"item": "_TEST-SE-LAPTOP", "voucher_no": entry.name},
			fields=["actual_qty", "is_cancelled"],
		)
		self.assertEqual(len(sles), 2)
		qtys = sorted(s.actual_qty for s in sles)
		self.assertEqual(qtys, [-10.0, 10.0])

	def test_cancel_consume_restores_balance(self):
		self._receipt("_TEST-SE-LAPTOP", 20, 500.0)
		entry = self._consume("_TEST-SE-LAPTOP", 8)
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 12)
		entry.cancel()
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 20)

	def test_cancel_transfer_restores_both_warehouses(self):
		self._receipt("_TEST-SE-CABLE", 30, 50.0)
		entry = self._transfer("_TEST-SE-CABLE", 10)
		entry.cancel()
		self.assertEqual(get_stock_balance("_TEST-SE-CABLE", "_Test SE Store"),   30)
		self.assertEqual(get_stock_balance("_TEST-SE-CABLE", "_Test SE Shelf A"), 0)

	# ── Validation edge-cases ──────────────────────────────────────────────────

	def test_receipt_without_to_warehouse_raises_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._make_entry("Receipt", [{"item": "_TEST-SE-LAPTOP", "qty": 1, "rate": 100}])

	def test_consume_without_from_warehouse_raises_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._make_entry("Consume", [{"item": "_TEST-SE-LAPTOP", "qty": 1}])

	def test_zero_qty_row_raises_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._receipt("_TEST-SE-LAPTOP", 0, 100.0)

	def test_empty_items_raises_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._make_entry("Receipt", [], to_wh="_Test SE Store")

	# ── Multi-item entry ───────────────────────────────────────────────────────

	def test_multi_item_receipt(self):
		doc = self._make_entry(
			"Receipt",
			[
				{"item": "_TEST-SE-LAPTOP", "qty": 5, "rate": 1000.0},
				{"item": "_TEST-SE-CABLE",  "qty": 20, "rate": 50.0},
			],
			to_wh="_Test SE Store",
		)
		self.assertEqual(get_stock_balance("_TEST-SE-LAPTOP", "_Test SE Store"), 5)
		self.assertEqual(get_stock_balance("_TEST-SE-CABLE",  "_Test SE Store"), 20)
		self.assertEqual(doc.total_amount, 6000.0)
