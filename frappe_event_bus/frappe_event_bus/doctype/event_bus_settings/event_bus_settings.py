"""Event Bus Settings single doctype controller."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class EventBusSettings(Document):
	"""Global settings for the event bus."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enable_delivery_logging: DF.Check
		enabled: DF.Check
		max_publish_attempts: DF.Int
		retention_days: DF.Int
		retry_backoff_seconds: DF.Int
		worker_batch_size: DF.Int
	# end: auto-generated types

	pass


def get_settings() -> "EventBusSettings":
	"""Return the cached Event Bus Settings single document."""
	return frappe.get_cached_doc("Event Bus Settings")
