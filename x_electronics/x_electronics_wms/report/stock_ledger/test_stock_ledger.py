import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today, nowtime

from x_electronics.x_electronics_wms.report.stock_ledger.stock_ledger import execute
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


class TestStockLedgerReport(IntegrationTestCase):

	def setUp(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TESTRPT-%"]})
		make_item("_TESTRPT-ITEM-A")
		make_item("_TESTRPT-ITEM-B")
		make_warehouse("_Test Rpt Root", is_group=1)
		make_warehouse("_Test Rpt WH1",  is_group=0, parent="_Test Rpt Root")
		make_warehouse("_Test Rpt WH2",  is_group=0, parent="_Test Rpt Root")

	def tearDown(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TESTRPT-%"]})

	def _post(self, item, wh, qty, rate, date=None):
		return post_stock_ledger_entry(
			item=item, warehouse=wh,
			actual_qty=qty, valuation_rate=rate,
			posting_date=date or today(),
			posting_time=nowtime(),
		)

	def _run(self, **filters):
		_columns, data = execute(filters)
		return data

	# ── column structure ───────────────────────────────────────────────────────

	def test_returns_expected_columns(self):
		columns, _ = execute({})
		fieldnames = [c["fieldname"] for c in columns]
		for expected in [
			"posting_date", "posting_time", "voucher_no",
			"item", "item_name", "warehouse",
			"qty_in", "qty_out", "balance_qty",
			"valuation_rate", "stock_value",
		]:
			self.assertIn(expected, fieldnames)

	# ── qty_in / qty_out split ─────────────────────────────────────────────────

	def test_receipt_row_has_qty_in_only(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		rows = self._run(item="_TESTRPT-ITEM-A", warehouse="_Test Rpt WH1")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].qty_in,  10)
		self.assertEqual(rows[0].qty_out,  0)

	def test_consume_row_has_qty_out_only(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1",  10, 100.0)
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1",  -4, 100.0)
		rows = self._run(item="_TESTRPT-ITEM-A", warehouse="_Test Rpt WH1")
		self.assertEqual(rows[1].qty_in,  0)
		self.assertEqual(rows[1].qty_out, 4)

	# ── running balance ────────────────────────────────────────────────────────

	def test_running_balance_increases_on_receipt(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 15, 100.0)
		rows = self._run(item="_TESTRPT-ITEM-A", warehouse="_Test Rpt WH1")
		self.assertEqual(rows[0].balance_qty, 10)
		self.assertEqual(rows[1].balance_qty, 25)

	def test_running_balance_decreases_on_consume(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 20, 100.0)
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", -8, 100.0)
		rows = self._run(item="_TESTRPT-ITEM-A", warehouse="_Test Rpt WH1")
		self.assertEqual(rows[0].balance_qty, 20)
		self.assertEqual(rows[1].balance_qty, 12)

	def test_running_balance_is_per_warehouse(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH2",  5, 100.0)
		rows = self._run(item="_TESTRPT-ITEM-A")
		wh1_rows = [r for r in rows if r.warehouse == "_Test Rpt WH1"]
		wh2_rows = [r for r in rows if r.warehouse == "_Test Rpt WH2"]
		self.assertEqual(wh1_rows[0].balance_qty, 10)
		self.assertEqual(wh2_rows[0].balance_qty,  5)

	# ── cumulative stock value ─────────────────────────────────────────────────

	def test_stock_value_reflects_cumulative_value(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)  # value = 1000
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 200.0)  # value += 2000
		rows = self._run(item="_TESTRPT-ITEM-A", warehouse="_Test Rpt WH1")
		self.assertAlmostEqual(rows[0].stock_value, 1000.0)
		self.assertAlmostEqual(rows[1].stock_value, 3000.0)

	def test_stock_value_drops_after_consume(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", -3, 100.0)
		rows = self._run(item="_TESTRPT-ITEM-A", warehouse="_Test Rpt WH1")
		self.assertAlmostEqual(rows[1].stock_value, 700.0)

	# ── date filter ────────────────────────────────────────────────────────────

	def test_from_date_filter_excludes_earlier_entries(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0, date="2020-01-01")
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1",  5, 100.0, date=today())
		rows = self._run(
			item="_TESTRPT-ITEM-A",
			warehouse="_Test Rpt WH1",
			from_date=today(),
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].qty_in, 5)

	def test_to_date_filter_excludes_later_entries(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1",  5, 100.0, date="2020-01-01")
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0, date=today())
		rows = self._run(
			item="_TESTRPT-ITEM-A",
			warehouse="_Test Rpt WH1",
			to_date="2020-01-01",
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].qty_in, 5)

	# ── multi-item / no-filter ─────────────────────────────────────────────────

	def test_no_filters_returns_all_items(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		self._post("_TESTRPT-ITEM-B", "_Test Rpt WH1",  5,  50.0)
		rows = self._run()
		items_in_result = {r.item for r in rows}
		self.assertIn("_TESTRPT-ITEM-A", items_in_result)
		self.assertIn("_TESTRPT-ITEM-B", items_in_result)

	def test_item_filter_returns_only_that_item(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		self._post("_TESTRPT-ITEM-B", "_Test Rpt WH1",  5,  50.0)
		rows = self._run(item="_TESTRPT-ITEM-A")
		self.assertTrue(all(r.item == "_TESTRPT-ITEM-A" for r in rows))

	def test_warehouse_filter_returns_only_that_warehouse(self):
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH1", 10, 100.0)
		self._post("_TESTRPT-ITEM-A", "_Test Rpt WH2",  3, 100.0)
		rows = self._run(warehouse="_Test Rpt WH1")
		self.assertTrue(all(r.warehouse == "_Test Rpt WH1" for r in rows))

	def test_empty_ledger_returns_no_rows(self):
		rows = self._run(item="_TESTRPT-ITEM-A")
		self.assertEqual(rows, [])
