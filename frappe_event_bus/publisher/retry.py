"""Scheduler-friendly entry point for draining the outbox."""

from __future__ import annotations

import frappe

from frappe_event_bus.frappe_event_bus.doctype.event_bus_settings.event_bus_settings import (
	get_settings,
)
from frappe_event_bus.publisher.outbox_worker import process_pending


def process_outbox() -> None:
	"""Scheduled task: process due outbox messages if the bus is enabled."""
	settings = get_settings()
	if not settings.enabled:
		return
	process_pending()
	# Scheduler tasks run outside a request, so commit to persist the results.
	frappe.db.commit()
