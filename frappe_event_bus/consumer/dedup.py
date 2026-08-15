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

#: A rendered key must contain no residual Jinja. frappe.render_template uses
#: jinja2.DebugUndefined, which stringifies an unresolved variable as
#: "{{ no such element: ... }}" rather than raising — and it does so even when
#: the rest of the expression resolved. Two different messages missing the same
#: field would then render an identical key and the second would be discarded as
#: a duplicate, so any residue at all forces the payload-hash fallback.
_UNRESOLVED_EXPRESSION_RE = re.compile(r"\{\{.*?\}\}")


def _plain(value: Any) -> dict[str, Any]:
	"""Strip a frappe._dict down to a plain dict before it reaches Jinja.

	frappe.parse_json wraps a decoded object in frappe._dict, whose
	``__getattr__`` is ``dict.get`` — a missing key returns ``None`` instead of
	raising ``AttributeError``. Jinja's dot lookup only falls through to
	``__getitem__`` (and from there to Undefined) when attribute access
	raises, so "{{ payload.missing }}" against a frappe._dict renders the
	literal text "None" and never reaches DebugUndefined at all — the
	``_UNRESOLVED_EXPRESSION_RE`` check above cannot see a failure that never
	produced "{{ ... }}" text. A plain dict has no such __getattr__, so the
	same lookup raises through to Undefined as expected.
	"""
	return dict(value or {})


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
		"payload": _plain(message.get("payload")),
		"headers": _plain(message.get("headers")),
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

	if _UNRESOLVED_EXPRESSION_RE.search(rendered):
		return None

	return rendered
