"""Deduplication key computation.

Deliberately free of doctype and database coupling so it unit-tests directly.

Every strategy falls back to the payload hash when it cannot produce a key. A
null or empty key would disable deduplication for that message, and redelivery
is normal operation in this design — so there is no safe way to fail open.

"Cannot produce a key" includes a payload that is valid JSON but not an object:
a broker may publish ``[1, 2, 3]`` or ``"hello"``, and neither has a named field
to read. ``as_mapping`` is the single shared guard for that.
"""

from __future__ import annotations

import hashlib
from typing import Any

from frappe_event_bus.consumer.expressions import as_mapping, render_key_expression


def payload_hash(message: dict[str, Any]) -> str:
	"""SHA-256 of the exact received body."""
	return hashlib.sha256((message.get("payload_raw") or "").encode()).hexdigest()


def compute_dedup_key(consumer: Any, message: dict[str, Any]) -> str:
	"""Return the deduplication key for ``message`` under ``consumer``'s strategy."""
	strategy = consumer.deduplication_strategy or "Payload Hash"
	expression = (consumer.deduplication_key_expression or "").strip()

	if strategy == "External Message ID":
		candidate = message.get("provider_message_id")
	elif strategy == "Header Value":
		candidate = as_mapping(message.get("headers")).get(expression)
	elif strategy == "Payload Field":
		candidate = as_mapping(message.get("payload")).get(expression)
	elif strategy == "Custom Expression":
		candidate = render_key_expression(
			expression, message.get("payload"), message.get("headers"), consumer
		)
	else:
		candidate = None

	candidate = str(candidate).strip() if candidate is not None else ""
	return candidate or payload_hash(message)
