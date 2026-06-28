"""Replay support: re-queue a previously terminal outbox message."""

from __future__ import annotations

from typing import Any

import frappe

REPLAYABLE_STATUSES = {"Failed", "Dead Lettered", "Published", "Cancelled", "Replayed"}


@frappe.whitelist()
def replay_outbox_message(name: str) -> dict[str, Any]:
	"""Reset a terminal outbox message back to Pending and enqueue the worker.

	Args:
		name: Outbox Message docname.

	Returns:
		Dict with the new status.
	"""
	outbox = frappe.get_doc("Event Bus Outbox Message", name)
	if outbox.status not in REPLAYABLE_STATUSES:
		frappe.throw(
			frappe._("Outbox Message '{0}' in status '{1}' cannot be replayed.").format(
				name, outbox.status
			)
		)

	outbox.status = "Pending"
	outbox.next_retry_at = None
	outbox.last_error = None
	outbox.published_at = None
	outbox.attempt_count = 0  # give the replayed message a fresh retry budget
	outbox.save(ignore_permissions=True)

	frappe.enqueue(
		"frappe_event_bus.publisher.outbox_worker.process_pending",
		queue="default",
		enqueue_after_commit=True,
	)
	return {"name": name, "status": outbox.status}
