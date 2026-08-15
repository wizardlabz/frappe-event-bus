"""Message-type detection.

Returns ``None`` rather than raising when the type cannot be determined. An
undetectable message type is a routing problem for the processing phase to
report, not a reason to reject a message the broker already delivered.
"""

from __future__ import annotations

from typing import Any


def detect_message_type(consumer: Any, message: dict[str, Any]) -> str | None:
	"""Return the message type for ``message`` under ``consumer``'s detection mode."""
	mode = consumer.message_type_detection or "Payload Field"
	source = (consumer.message_type_source or "").strip()

	if mode == "Fixed":
		return source or None
	if mode == "Routing Key":
		return message.get("routing_key") or None
	if mode == "Header":
		value = (message.get("headers") or {}).get(source)
	else:
		value = (message.get("payload") or {}).get(source)

	return str(value) if value is not None else None
