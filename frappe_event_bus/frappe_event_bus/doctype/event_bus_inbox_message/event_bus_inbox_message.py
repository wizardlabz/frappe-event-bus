"""Event Bus Inbox Message controller."""

from __future__ import annotations

from frappe.model.document import Document


class EventBusInboxMessage(Document):
	"""A message received from a broker and persisted before acknowledgement.

	Phase A assigns only ``Received`` and ``Ignored``. The remaining statuses
	exist on the field so the processing phase adds behaviour, not a migration.
	"""

	pass
