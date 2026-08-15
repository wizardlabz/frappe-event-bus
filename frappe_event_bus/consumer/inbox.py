"""Inbox persistence.

Deduplication is enforced by the UNIQUE index on ``deduplication_key``, not by
a lookup before insert. A read-then-write races: two pollers can both find a
key absent and both insert it. With the index, the insert either succeeds or
raises, and the raise is the detection.

Duplicate rows store the key in ``duplicate_key`` and leave the indexed column
NULL, so many duplicates coexist while originals stay unique.

This module is also the only one that knows how wide the Inbox's columns are,
so it is where an over-long computed value is turned back into a storable one
(see :func:`_fitting`) rather than into an insert that can never succeed.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import cint, cstr, now_datetime

from frappe_event_bus.consumer.dedup import compute_dedup_key, payload_hash
from frappe_event_bus.consumer.detection import detect_message_type
from frappe_event_bus.consumer.expressions import render_key_expression

DOCTYPE = "Event Bus Inbox Message"


def persist_message(consumer: Any, message: dict[str, Any]) -> Document:
	"""Write ``message`` to the Inbox, as Received or as an Ignored duplicate."""
	dedup_key = compute_dedup_key(consumer, message)
	# A key that does not fit its column makes the message permanently
	# unpersistable: _validate_length raises, the row never lands, the worker
	# never acknowledges it, and the broker redelivers it every cycle forever
	# with no operator action able to clear it. The payload hash is 64 hex
	# characters, always fits, and is the fallback every other unusable
	# deduplication key already takes.
	dedup_key = _fitting(dedup_key, "deduplication_key", payload_hash(message))
	values = _row_values(consumer, message, dedup_key)

	# Own savepoint: a failed unique insert must be rolled back before the
	# retry insert, and this function is called directly (by tests and by the
	# poll loop alike), so it cannot rely on a caller having opened one.
	frappe.db.savepoint("eb_inbox_dedup")
	try:
		return frappe.get_doc(values).insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Redelivery: the broker sent a message we already hold. Recording it
		# keeps the redelivery visible instead of silently swallowing it.
		frappe.db.rollback(save_point="eb_inbox_dedup")
		original = frappe.db.get_value(DOCTYPE, {"deduplication_key": dedup_key}, "name")
		values.update(
			{
				"status": "Ignored",
				"deduplication_key": None,
				"duplicate_key": dedup_key,
				"duplicate_of": original,
			}
		)
		return frappe.get_doc(values).insert(ignore_permissions=True)


def _column_limit(fieldname: str) -> int:
	"""Characters ``fieldname`` can hold, by the same rule Frappe validates with.

	Read from the meta rather than hard-coded so the guard cannot drift from the
	schema if a column is ever widened: this is exactly what
	``Document._validate_length`` computes before raising
	``CharacterLengthExceededError``.
	"""
	field = frappe.get_meta(DOCTYPE).get_field(fieldname)
	return cint(field.get("length")) or cint(frappe.db.type_map[field.fieldtype][1])


def _fitting(value: Any, fieldname: str, fallback: Any = None) -> Any:
	"""Return ``value`` if it fits ``fieldname``'s column, else ``fallback``.

	Every caller supplies a fallback that always fits, because the alternative
	is a row that can never be inserted and therefore a message that is never
	acknowledged and redelivered forever.
	"""
	return value if len(cstr(value)) <= _column_limit(fieldname) else fallback


def _row_values(consumer: Any, message: dict[str, Any], dedup_key: str) -> dict[str, Any]:
	"""Build the Inbox row for a freshly received message."""
	return {
		"doctype": DOCTYPE,
		"consumer": consumer.name,
		"provider": consumer.provider,
		# Both fall back to something the consumer's own configuration
		# guarantees fits: these two values come from the provider, so their
		# length is not this app's to promise.
		"source": _fitting(message.get("source") or consumer.source, "source", consumer.source),
		"external_message_id": _fitting(message.get("provider_message_id"), "external_message_id"),
		# An over-long type is dropped rather than truncated: a truncated type
		# is a plausible-looking wrong answer that a later phase would route on,
		# whereas None is the "undetectable type" outcome detection already
		# documents and the processing phase already has to handle.
		"message_type": _fitting(detect_message_type(consumer, message), "message_type"),
		"payload": message.get("payload_raw") or "",
		"headers": json.dumps(message.get("headers") or {}),
		"raw_metadata": json.dumps(message.get("raw_metadata") or {}),
		"status": "Received",
		"deduplication_key": dedup_key,
		"ordering_key": _ordering_key(consumer, message, dedup_key),
		"attempt_count": 0,
		"received_at": now_datetime(),
	}


def _ordering_key(consumer: Any, message: dict[str, Any], dedup_key: str) -> str:
	"""Ordering key, defaulting to the deduplication key.

	Stored but unused in this phase: the processing phase serializes on it. An
	over-long rendered key takes the same fallback as an unusable one — the
	deduplication key, which by this point is guaranteed to fit.
	"""
	rendered = render_key_expression(
		consumer.ordering_key_expression,
		message.get("payload"),
		message.get("headers"),
		consumer,
	)
	return _fitting(rendered, "ordering_key", dedup_key) or dedup_key
