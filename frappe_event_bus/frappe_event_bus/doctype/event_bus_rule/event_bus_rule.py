"""Event Bus Rule controller."""

from __future__ import annotations

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

	pass
