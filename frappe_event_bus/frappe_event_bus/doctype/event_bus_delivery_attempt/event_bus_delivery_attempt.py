"""Event Bus Delivery Attempt controller."""

from __future__ import annotations

from frappe.model.document import Document


class EventBusDeliveryAttempt(Document):
	"""Records a single publish attempt for an outbox message."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attempt_number: DF.Int
		completed_at: DF.Datetime | None
		duration_ms: DF.Int
		error_message: DF.SmallText | None
		outbox_message: DF.Link | None
		provider: DF.Data | None
		provider_response: DF.Code | None
		started_at: DF.Datetime | None
		success: DF.Check
	# end: auto-generated types

	pass
