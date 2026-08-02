"""Event Bus Rule controller."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class EventBusRule(Document):
	"""Maps a document event to a message template and a set of destinations."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from frappe_event_bus.frappe_event_bus.doctype.event_bus_rule_destination.event_bus_rule_destination import (
			EventBusRuleDestination,
		)

		condition: DF.Code | None
		deduplication_key_template: DF.Data | None
		description: DF.SmallText | None
		destinations: DF.Table[EventBusRuleDestination]
		enabled: DF.Check
		event_type: DF.Literal["after_insert", "on_update", "on_submit", "on_cancel", "on_trash"]
		message_template: DF.Link
		reference_doctype: DF.Link
		rule_name: DF.Data
	# end: auto-generated types

	def validate(self) -> None:
		"""Reject a template bound to a different doctype than this rule targets."""
		self._validate_template_binding()

	def _validate_template_binding(self) -> None:
		"""Throw if the linked template declares a conflicting ``applies_to_doctype``.

		A template with a blank ``applies_to_doctype`` is generic and matches any
		rule. Catching a mismatch here turns a silent background-job render
		failure into an error at save time.
		"""
		if not self.message_template:
			return

		applies_to = frappe.db.get_value(
			"Event Bus Message Template", self.message_template, "applies_to_doctype"
		)
		if applies_to and applies_to != self.reference_doctype:
			frappe.throw(
				frappe._("Message Template {0} applies to {1}, but this rule targets {2}.").format(
					self.message_template, applies_to, self.reference_doctype
				),
				title=frappe._("Template DocType Mismatch"),
			)
