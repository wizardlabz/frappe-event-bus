"""Event Bus Consumer controller."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class EventBusConsumer(Document):
	"""A configured source of inbound messages."""

	def validate(self) -> None:
		self._reject_unimplemented_consumption_mode()

	def _reject_unimplemented_consumption_mode(self) -> None:
		"""Fail loudly rather than silently never polling.

		The field carries both modes because the plan defines both, but only
		Scheduled Polling is implemented. A consumer saved as Dedicated Worker
		would otherwise look configured and never receive anything.
		"""
		if self.consumption_mode == "Dedicated Worker":
			frappe.throw(
				frappe._("Dedicated Worker consumption mode is not available yet. Use Scheduled Polling.")
			)
