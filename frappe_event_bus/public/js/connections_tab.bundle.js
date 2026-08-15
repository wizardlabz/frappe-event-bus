/**
 * Move the form dashboard into a dedicated "Connections" tab.
 *
 * Frappe renders connections as a collapsible section pinned above the form
 * body (see form/dashboard.js — it only ever calls make_section). On a doctype
 * with tabs that buries related documents under whichever tab happens to be
 * open, so the dashboard is relocated into a tab of its own.
 *
 * Applies to every Event Bus doctype that declares `links`.
 */

const DOCTYPES = [
	"Event Bus Rule",
	"Event Bus Message Template",
	"Event Bus Outbox Message",
	"RabbitMQ Event Bus Connection",
	"RabbitMQ Event Bus Destination",
];

function moveDashboardIntoTab(frm) {
	const field = frm.get_field("connections_html");
	if (!field || !frm.$wrapper) return;

	const dashboard = frm.$wrapper.find(".form-dashboard").first();
	if (!dashboard.length) return;

	// Already parked in the tab — appending again is a no-op move, but skip the
	// DOM churn on every refresh.
	if (field.$wrapper.find(".form-dashboard").length) return;

	field.$wrapper.append(dashboard);

	// Link counts are normally fetched by an IntersectionObserver that fires
	// when the links area scrolls into view (dashboard.js: observe_link_render).
	// Inside a tab that starts hidden it never intersects, so the badges stay
	// empty forever — fetch them explicitly instead.
	if (frm.dashboard && !frm.dashboard._fetched_counts) {
		frm.dashboard.set_open_count();
	}
}

for (const doctype of DOCTYPES) {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			// The dashboard is populated asynchronously after refresh, so let
			// that settle before relocating it.
			setTimeout(() => moveDashboardIntoTab(frm), 300);
		},
	});
}
