"""Event Bus Consumer controller."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

#: Strategies whose key is read from, or rendered with, the deduplication key
#: expression. Each is meaningless without one.
EXPRESSION_STRATEGIES = ("Header Value", "Payload Field", "Custom Expression")


class EventBusConsumer(Document):
	"""A configured source of inbound messages."""

	def validate(self) -> None:
		self._reject_unimplemented_consumption_mode()
		self._require_deduplication_key_expression()

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

	def _require_deduplication_key_expression(self) -> None:
		"""Fail loudly rather than silently deduplicating on something else.

		Three of the five strategies have nothing to read without an
		expression. Left blank, they do not fail — they look up the empty
		string, find nothing, and fall back to the payload hash, so the
		consumer silently deduplicates on the message body instead of the key
		it was configured for. Under the Inbox's global deduplication scope
		that is not a harmless downgrade: two genuinely distinct messages with
		identical bodies (a repeated heartbeat) then collide, and the second is
		stored as Ignored and never processed.
		"""
		if self.deduplication_strategy not in EXPRESSION_STRATEGIES:
			return
		if (self.deduplication_key_expression or "").strip():
			return
		frappe.throw(
			frappe._("Deduplication Key Expression is required when Deduplication Strategy is {0}.").format(
				frappe._(self.deduplication_strategy)
			)
		)
