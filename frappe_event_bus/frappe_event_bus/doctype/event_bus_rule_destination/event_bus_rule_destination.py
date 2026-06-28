"""Event Bus Rule Destination child table controller."""

from __future__ import annotations

from frappe.model.document import Document


class EventBusRuleDestination(Document):
	"""A single publishing target attached to an Event Bus Rule."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		connection: DF.Data
		destination: DF.Data
		enabled: DF.Check
		headers_template: DF.Code | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		priority: DF.Int
		provider: DF.Data
		routing_key: DF.Data | None
	# end: auto-generated types

	pass
