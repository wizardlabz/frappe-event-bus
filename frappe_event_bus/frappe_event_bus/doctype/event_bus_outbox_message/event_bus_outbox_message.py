"""Event Bus Outbox Message controller."""

from __future__ import annotations

from frappe.model.document import Document


class EventBusOutboxMessage(Document):
	"""A queued message awaiting (or having completed) delivery to a provider."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attempt_count: DF.Int
		connection: DF.Data | None
		deduplication_key: DF.Data | None
		destination: DF.Data | None
		event_rule: DF.Link | None
		event_type: DF.Data | None
		headers: DF.Code | None
		last_error: DF.SmallText | None
		message_template: DF.Link | None
		next_retry_at: DF.Datetime | None
		payload: DF.Code | None
		provider: DF.Data | None
		published_at: DF.Datetime | None
		reference_doctype: DF.Data | None
		reference_document: DF.Data | None
		routing_key: DF.Data | None
		status: DF.Literal[
			"Pending",
			"Publishing",
			"Published",
			"Retry Scheduled",
			"Failed",
			"Dead Lettered",
			"Cancelled",
			"Replayed",
		]
	# end: auto-generated types

	pass
