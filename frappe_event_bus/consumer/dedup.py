"""Deduplication key computation.

Deliberately free of doctype and database coupling so it unit-tests directly.

Every strategy falls back to the payload hash when it cannot produce a key. A
null or empty key would disable deduplication for that message, and redelivery
is normal operation in this design — so there is no safe way to fail open.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import frappe

# frappe.render_template renders with jinja2.DebugUndefined, which stringifies
# an unresolved variable as "{{ ... }}" instead of raising or returning an
# empty string. A fully-unresolved render must be treated the same as a
# raised error so a missing field falls back to the payload hash rather than
# becoming the dedup key itself.
_UNRESOLVED_EXPRESSION_RE = re.compile(r"^\{\{ .+ \}\}$")


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
		candidate = (message.get("headers") or {}).get(expression)
	elif strategy == "Payload Field":
		candidate = (message.get("payload") or {}).get(expression)
	elif strategy == "Custom Expression":
		candidate = _render_expression(expression, consumer, message)
	else:
		candidate = None

	candidate = str(candidate).strip() if candidate is not None else ""
	return candidate or payload_hash(message)


def _render_expression(expression: str, consumer: Any, message: dict[str, Any]) -> str | None:
	"""Render a Jinja key expression, returning None when it cannot be used."""
	if not expression:
		return None
	context = {
		"payload": message.get("payload") or {},
		"headers": message.get("headers") or {},
		"consumer": consumer,
	}
	try:
		rendered = frappe.render_template(expression, context).strip()
	except Exception:
		frappe.log_error(
			title="Event Bus: deduplication key expression failed",
			message=frappe.get_traceback(),
		)
		return None

	if _UNRESOLVED_EXPRESSION_RE.match(rendered):
		return None

	return rendered
