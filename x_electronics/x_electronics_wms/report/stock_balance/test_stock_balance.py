import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from x_electronics.x_electronics_wms.report.stock_balance.stock_balance import execute
from x_electronics.x_electronics_wms.utils import post_stock_ledger_entry


def make_item(code):
	if not frappe.db.exists("Item", code):
		frappe.get_doc({
			"doctype": "Item", "item_code": code,
			"item_name": code, "uom": "Nos",
		}).insert(ignore_permissions=True)


def make_warehouse(name, is_group=0, parent=None):
	if not frappe.db.exists("Warehouse", name):
		frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": name,
			"is_group": is_group, "parent_warehouse": parent,
		}).insert(ignore_permissions=True)


def setup_tree():
	"""
	_Test SB Root (group)
	├── _Test SB WH A  (leaf)
	└── _Test SB WH B  (leaf)
	"""
	make_warehouse("_Test SB Root",  is_group=1)
	make_warehouse("_Test SB WH A",  is_group=0, parent="_Test SB Root")
	make_warehouse("_Test SB WH B",  is_group=0, parent="_Test SB Root")
	make_item("_TESTSB-ITEM-X")
	make_item("_TESTSB-ITEM-Y")


class TestStockBalanceReport(IntegrationTestCase):

	def setUp(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TESTSB-%"]})
		setup_tree()

	def tearDown(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TESTSB-%"]})

	# ── helpers ────────────────────────────────────────────────────────────────

	def _post(self, item, wh, qty, rate, date=None):
		post_stock_ledger_entry(
			item=item, warehouse=wh,
			actual_qty=qty, valuation_rate=rate,
			posting_date=date or today(),
			posting_time="10:00:00",
		)

	def _run(self, **filters):
		_cols, data = execute(filters)
		return data

	def _row(self, data, item, warehouse):
		"""Find a specific row by item + warehouse."""
		matches = [r for r in data if r.item == item and r.warehouse == warehouse]
		self.assertEqual(len(matches), 1, f"Expected 1 row for {item}/{warehouse}, got {len(matches)}")
		return matches[0]

	# ── column structure ───────────────────────────────────────────────────────

	def test_returns_expected_columns(self):
		columns, _ = execute({})
		fieldnames = [c["fieldname"] for c in columns]
		for expected in ["item", "item_name", "warehouse",
						 "balance_qty", "valuation_rate", "stock_value"]:
			self.assertIn(expected, fieldnames)

	# ── point-in-time accuracy ─────────────────────────────────────────────────

	def test_balance_reflects_receipts_as_of_date(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0, date="2024-01-01")
		self._post("_TESTSB-ITEM-X", "_Test SB WH A",  5, 120.0, date="2024-06-01")
		row = self._row(
			self._run(as_of_date="2024-01-01", item="_TESTSB-ITEM-X"),
			"_TESTSB-ITEM-X", "_Test SB WH A",
		)
		self.assertEqual(row.balance_qty, 10)

	def test_future_entries_excluded_from_balance(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 20, 100.0, date="2025-01-01")
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0, date="2030-01-01")
		data = self._run(as_of_date="2025-12-31", item="_TESTSB-ITEM-X")
		row = self._row(data, "_TESTSB-ITEM-X", "_Test SB WH A")
		self.assertEqual(row.balance_qty, 20)

	def test_zero_balance_items_excluded(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A",  10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", -10, 100.0)
		data = self._run(item="_TESTSB-ITEM-X")
		self.assertEqual(data, [])

	def test_valuation_rate_is_moving_average(self):
		# 10 @ 100 + 10 @ 200  → avg = 150
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 200.0)
		row = self._row(self._run(item="_TESTSB-ITEM-X"), "_TESTSB-ITEM-X", "_Test SB WH A")
		self.assertAlmostEqual(row.valuation_rate, 150.0)

	def test_stock_value_equals_qty_times_avg_rate(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 200.0)
		row = self._row(self._run(item="_TESTSB-ITEM-X"), "_TESTSB-ITEM-X", "_Test SB WH A")
		self.assertAlmostEqual(row.stock_value, 3000.0)

	# ── filters ────────────────────────────────────────────────────────────────

	def test_item_filter_returns_only_that_item(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-Y", "_Test SB WH A",  5,  50.0)
		data = self._run(item="_TESTSB-ITEM-X")
		self.assertTrue(all(r.item == "_TESTSB-ITEM-X" for r in data))

	def test_leaf_warehouse_filter_returns_only_that_warehouse(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH B",  5, 100.0)
		data = self._run(warehouse="_Test SB WH A")
		self.assertTrue(all(r.warehouse == "_Test SB WH A" for r in data))

	def test_no_filter_returns_all_warehouses(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH B",  5, 100.0)
		data = self._run(item="_TESTSB-ITEM-X")
		warehouses = {r.warehouse for r in data}
		self.assertIn("_Test SB WH A", warehouses)
		self.assertIn("_Test SB WH B", warehouses)

	def test_empty_ledger_returns_no_rows(self):
		data = self._run(item="_TESTSB-ITEM-X")
		self.assertEqual(data, [])

	# ── tree consolidation ─────────────────────────────────────────────────────

	def test_group_warehouse_filter_includes_all_children(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH B",  5, 100.0)
		data = self._run(warehouse="_Test SB Root", item="_TESTSB-ITEM-X")
		leaf_warehouses = {r.warehouse for r in data if not r.get("is_group_total")}
		self.assertIn("_Test SB WH A", leaf_warehouses)
		self.assertIn("_Test SB WH B", leaf_warehouses)

	def test_group_filter_appends_consolidated_summary_row(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH B",  5, 100.0)
		data = self._run(warehouse="_Test SB Root", item="_TESTSB-ITEM-X")
		summary = [r for r in data if r.get("is_group_total")]
		self.assertEqual(len(summary), 1)
		self.assertEqual(summary[0].warehouse, "_Test SB Root")
		self.assertEqual(summary[0].balance_qty, 15)

	def test_consolidated_stock_value_equals_sum_of_children(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 200.0)  # value = 2000
		self._post("_TESTSB-ITEM-X", "_Test SB WH B",  5, 200.0)  # value = 1000
		data = self._run(warehouse="_Test SB Root", item="_TESTSB-ITEM-X")
		summary = next(r for r in data if r.get("is_group_total"))
		self.assertAlmostEqual(summary.stock_value, 3000.0)

	def test_consolidation_with_multiple_items(self):
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-Y", "_Test SB WH B",  8,  50.0)
		data = self._run(warehouse="_Test SB Root")
		summaries = [r for r in data if r.get("is_group_total")]
		summary_items = {r.item for r in summaries}
		self.assertIn("_TESTSB-ITEM-X", summary_items)
		self.assertIn("_TESTSB-ITEM-Y", summary_items)

	def test_consolidated_valuation_rate_is_weighted_average(self):
		# WH A: 10 @ 100 = 1000,  WH B: 10 @ 200 = 2000
		# consolidated avg = 3000 / 20 = 150
		self._post("_TESTSB-ITEM-X", "_Test SB WH A", 10, 100.0)
		self._post("_TESTSB-ITEM-X", "_Test SB WH B", 10, 200.0)
		data = self._run(warehouse="_Test SB Root", item="_TESTSB-ITEM-X")
		summary = next(r for r in data if r.get("is_group_total"))
		self.assertAlmostEqual(summary.valuation_rate, 150.0)
