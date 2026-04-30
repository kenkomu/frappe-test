import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today, nowtime

from x_electronics.x_electronics_wms.utils import (
	get_moving_avg_valuation,
	get_stock_balance,
	get_valuation_rate,
	post_stock_ledger_entry,
)


def make_item(item_code, item_name="Test Item"):
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc({
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_name,
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
	return name


class TestStockLedgerEntry(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TEST-%"]})
		make_item("_TEST-SLE-ITEM")
		make_warehouse("_Test SLE Root", is_group=1)
		make_warehouse("_Test SLE WH", is_group=0, parent="_Test SLE Root")

	def tearDown(self):
		frappe.db.delete("Stock Ledger Entry", {"item": ["like", "_TEST-%"]})

	def _post(self, qty, rate, item="_TEST-SLE-ITEM", wh="_Test SLE WH"):
		return post_stock_ledger_entry(
			item=item,
			warehouse=wh,
			actual_qty=qty,
			valuation_rate=rate,
			posting_date=today(),
			posting_time=nowtime(),
		)

	# ── stock_value_difference ─────────────────────────────────────────────────

	def test_stock_value_difference_computed_on_insert(self):
		sle = self._post(10, 100.0)
		self.assertEqual(sle.stock_value_difference, 1000.0)

	def test_negative_qty_gives_negative_value_difference(self):
		self._post(10, 100.0)
		sle = self._post(-4, 100.0)
		self.assertEqual(sle.stock_value_difference, -400.0)

	# ── get_stock_balance ──────────────────────────────────────────────────────

	def test_balance_is_zero_before_any_entry(self):
		self.assertEqual(get_stock_balance("_TEST-SLE-ITEM", "_Test SLE WH"), 0)

	def test_balance_after_receipt(self):
		self._post(15, 50.0)
		self.assertEqual(get_stock_balance("_TEST-SLE-ITEM", "_Test SLE WH"), 15)

	def test_balance_after_receipt_and_consume(self):
		self._post(20, 50.0)
		self._post(-8, 50.0)
		self.assertEqual(get_stock_balance("_TEST-SLE-ITEM", "_Test SLE WH"), 12)

	def test_balance_as_of_past_date_excludes_future_entries(self):
		past = "2020-01-01"
		post_stock_ledger_entry(
			item="_TEST-SLE-ITEM",
			warehouse="_Test SLE WH",
			actual_qty=100,
			valuation_rate=10.0,
			posting_date=past,
			posting_time="10:00:00",
		)
		# today's entry should not show in the 2020 balance
		self._post(50, 10.0)
		balance_2020 = get_stock_balance("_TEST-SLE-ITEM", "_Test SLE WH", posting_date=past)
		self.assertEqual(balance_2020, 100)

	# ── get_valuation_rate ─────────────────────────────────────────────────────

	def test_valuation_rate_zero_when_no_stock(self):
		self.assertEqual(get_valuation_rate("_TEST-SLE-ITEM", "_Test SLE WH"), 0.0)

	def test_valuation_rate_equals_receipt_rate_for_first_receipt(self):
		self._post(10, 200.0)
		self.assertAlmostEqual(get_valuation_rate("_TEST-SLE-ITEM", "_Test SLE WH"), 200.0)

	# ── get_moving_avg_valuation ───────────────────────────────────────────────

	def test_moving_avg_first_receipt_returns_incoming_rate(self):
		rate = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 10, 100.0)
		self.assertAlmostEqual(rate, 100.0)

	def test_moving_avg_two_receipts_same_rate(self):
		self._post(10, 100.0)
		rate = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 10, 100.0)
		self.assertAlmostEqual(rate, 100.0)

	def test_moving_avg_two_receipts_different_rates(self):
		# 10 units @ 100 → stock_value = 1000
		self._post(10, 100.0)
		# incoming: 10 units @ 200 → new total = (1000 + 2000) / 20 = 150
		rate = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 10, 200.0)
		self.assertAlmostEqual(rate, 150.0)

	def test_moving_avg_three_receipts_at_different_rates(self):
		# SLE stores the INCOMING purchase rate, so the formula
		# SUM(stock_value_difference) / SUM(actual_qty) always yields the
		# correct moving average.

		# receipt 1: 10 @ 100 — no prior stock, predicted avg = 100
		r1 = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 10, 100.0)
		self.assertAlmostEqual(r1, 100.0)
		self._post(10, 100.0)  # post at incoming rate, DB: qty=10, value=1000

		# receipt 2: 10 @ 200 — predicted avg = (1000+2000)/20 = 150
		r2 = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 10, 200.0)
		self.assertAlmostEqual(r2, 150.0)
		self._post(10, 200.0)  # post at incoming rate, DB: qty=20, value=3000

		# receipt 3: 20 @ 300 — predicted avg = (3000+6000)/40 = 225
		r3 = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 20, 300.0)
		self.assertAlmostEqual(r3, 225.0)

	def test_moving_avg_unaffected_by_consume_qty(self):
		# consume does not change the avg rate (it just reduces qty)
		self._post(20, 100.0)
		self._post(-5, 100.0)  # consume 5 units at existing rate
		# now: qty=15, value=1500, avg still 100
		# incoming 5 @ 200 → (1500 + 1000) / 20 = 125
		rate = get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 5, 200.0)
		self.assertAlmostEqual(rate, 125.0)

	def test_moving_avg_raises_for_zero_incoming_qty(self):
		with self.assertRaises(frappe.ValidationError):
			get_moving_avg_valuation("_TEST-SLE-ITEM", "_Test SLE WH", 0, 100.0)

	# ── SLE validation ─────────────────────────────────────────────────────────

	def test_cannot_post_to_group_warehouse(self):
		with self.assertRaises(frappe.ValidationError):
			self._post(10, 100.0, wh="_Test SLE Root")  # is_group=1

	def test_cannot_post_for_inactive_item(self):
		make_item("_TEST-SLE-INACTIVE")
		frappe.db.set_value("Item", "_TEST-SLE-INACTIVE", "is_active", 0)
		with self.assertRaises(frappe.ValidationError):
			self._post(10, 100.0, item="_TEST-SLE-INACTIVE")
