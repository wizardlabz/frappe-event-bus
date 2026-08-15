"""Message-type detection.

Returns ``None`` rather than raising when the type cannot be determined. An
undetectable message type is a routing problem for the processing phase to
report, not a reason to reject a message the broker already delivered.

That includes a payload or header set that is valid JSON but not an object —
``[1, 2, 3]`` and ``"hello"`` have no named field to read. ``as_mapping`` is the
single shared guard for that.
"""

from __future__ import annotations

from typing import Any

from frappe_event_bus.consumer.expressions import as_mapping


def detect_message_type(consumer: Any, message: dict[str, Any]) -> str | None:
	"""Return the message type for ``message`` under ``consumer``'s detection mode."""
	mode = consumer.message_type_detection or "Payload Field"
	source = (consumer.message_type_source or "").strip()

	if mode == "Fixed":
		return source or None
	if mode == "Routing Key":
		return message.get("routing_key") or None
	if mode == "Header":
		value = as_mapping(message.get("headers")).get(source)
	else:
		value = as_mapping(message.get("payload")).get(source)

	return str(value) if value is not None else None
