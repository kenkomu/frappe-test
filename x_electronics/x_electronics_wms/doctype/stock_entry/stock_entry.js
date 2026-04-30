frappe.ui.form.on('Stock Entry', {

	stock_entry_type(frm) {
		frm.trigger('toggle_warehouse_fields');
	},

	refresh(frm) {
		frm.trigger('toggle_warehouse_fields');
	},

	toggle_warehouse_fields(frm) {
		const t = frm.doc.stock_entry_type;
		const show_from = ['Consume', 'Transfer'].includes(t);
		const show_to   = ['Receipt',  'Transfer'].includes(t);

		frm.toggle_reqd('from_warehouse', show_from);
		frm.toggle_reqd('to_warehouse',   show_to);
		frm.toggle_display('from_warehouse', show_from);
		frm.toggle_display('to_warehouse',   show_to);
	},
});

frappe.ui.form.on('Stock Entry Detail', {

	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item) return;

		// Auto-fill rate from current valuation when consuming/transferring
		if (['Consume', 'Transfer'].includes(frm.doc.stock_entry_type)) {
			const src = row.from_warehouse || frm.doc.from_warehouse;
			if (!src) return;

			frappe.call({
				method: 'x_electronics.x_electronics_wms.utils.get_valuation_rate',
				args: { item: row.item, warehouse: src },
				callback(r) {
					if (r.message !== undefined) {
						frappe.model.set_value(cdt, cdn, 'rate', r.message);
					}
				},
			});
		}
	},

	qty(frm, cdt, cdn) {
		calculate_amount(cdt, cdn);
	},

	rate(frm, cdt, cdn) {
		calculate_amount(cdt, cdn);
	},
});

function calculate_amount(cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, 'amount', (row.qty || 0) * (row.rate || 0));
}
