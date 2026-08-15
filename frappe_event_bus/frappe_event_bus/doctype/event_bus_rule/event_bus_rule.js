/**
 * Event Bus Rule form behaviour.
 *
 * Restricts the Message Template link to templates that either target this
 * rule's Reference DocType or are generic, and pre-binds newly created
 * templates to it.
 */

frappe.ui.form.on("Event Bus Rule", {
	onload(frm) {
		frm.set_query("message_template", () => {
			if (!frm.doc.reference_doctype) return {};
			return {
				filters: [["applies_to_doctype", "in", [frm.doc.reference_doctype, ""]]],
			};
		});

		// Frappe reads this off the docfield, not the control (link.js:187).
		const field = frm.fields_dict.message_template;
		if (field) {
			field.df.get_route_options_for_new_doc = () => ({
				applies_to_doctype: frm.doc.reference_doctype || "",
			});
		}
	},

	reference_doctype(frm) {
		// A template bound to the old doctype can no longer be valid here.
		if (frm.doc.message_template) {
			frm.set_value("message_template", null);
		}
	},
});
