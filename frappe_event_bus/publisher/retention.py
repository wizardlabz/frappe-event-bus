"""Bounded outbox growth: purge old succeeded messages on a schedule.

Only terminal *successful* states are purged. Failed, Dead Lettered and
Retry Scheduled rows are kept regardless of age — retention exists to stop the
table growing without bound, not to delete the evidence you need when a
delivery goes wrong.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime

from frappe_event_bus.frappe_event_bus.doctype.event_bus_settings.event_bus_settings import (
	get_settings,
)

#: Statuses safe to delete once they age out.
PURGEABLE_STATUSES = ("Published", "Cancelled")


def purge_old_messages() -> dict[str, int]:
	"""Delete aged-out succeeded outbox messages and their delivery attempts.

	Retention is read from Event Bus Settings; ``0`` (or blank) disables
	purging entirely.

	Returns:
		Counts of deleted rows, as ``{"messages": int, "attempts": int}``.
	"""
	retention_days = int(get_settings().retention_days or 0)
	if retention_days <= 0:
		return {"messages": 0, "attempts": 0}

	cutoff = add_days(now_datetime(), -retention_days)
	names = frappe.get_all(
		"Event Bus Outbox Message",
		filters=[
			["status", "in", list(PURGEABLE_STATUSES)],
			["modified", "<", cutoff],
		],
		pluck="name",
	)
	if not names:
		return {"messages": 0, "attempts": 0}

	attempts = frappe.get_all(
		"Event Bus Delivery Attempt", filters=[["outbox_message", "in", names]], pluck="name"
	)

	# Delete attempts first so nothing is left pointing at a missing message.
	if attempts:
		frappe.db.delete("Event Bus Delivery Attempt", {"outbox_message": ("in", names)})
	frappe.db.delete("Event Bus Outbox Message", {"name": ("in", names)})

	return {"messages": len(names), "attempts": len(attempts)}


def purge_outbox() -> None:
	"""Scheduled task entry point: purge if the bus is enabled."""
	settings = get_settings()
	if not settings.enabled:
		return
	result = purge_old_messages()
	# Scheduler tasks run outside a request, so commit to persist the deletes.
	frappe.db.commit()
	if result["messages"]:
		frappe.logger("frappe_event_bus").info(
			f"Purged {result['messages']} outbox messages and {result['attempts']} attempts"
		)
