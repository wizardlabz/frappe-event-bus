"""Inbox persistence.

Deduplication is enforced by the UNIQUE index on ``deduplication_key``, not by
a lookup before insert. A read-then-write races: two pollers can both find a
key absent and both insert it. With the index, the insert either succeeds or
raises, and the raise is the detection.

Duplicate rows store the key in ``duplicate_key`` and leave the indexed column
NULL, so many duplicates coexist while originals stay unique.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from frappe_event_bus.consumer.dedup import compute_dedup_key
from frappe_event_bus.consumer.detection import detect_message_type
from frappe_event_bus.consumer.expressions import render_key_expression


def persist_message(consumer: Any, message: dict[str, Any]) -> Document:
	"""Write ``message`` to the Inbox, as Received or as an Ignored duplicate."""
	dedup_key = compute_dedup_key(consumer, message)
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
		original = frappe.db.get_value("Event Bus Inbox Message", {"deduplication_key": dedup_key}, "name")
		values.update(
			{
				"status": "Ignored",
				"deduplication_key": None,
				"duplicate_key": dedup_key,
				"duplicate_of": original,
			}
		)
		return frappe.get_doc(values).insert(ignore_permissions=True)


def _row_values(consumer: Any, message: dict[str, Any], dedup_key: str) -> dict[str, Any]:
	"""Build the Inbox row for a freshly received message."""
	return {
		"doctype": "Event Bus Inbox Message",
		"consumer": consumer.name,
		"provider": consumer.provider,
		"source": message.get("source") or consumer.source,
		"external_message_id": message.get("provider_message_id"),
		"message_type": detect_message_type(consumer, message),
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

	Stored but unused in this phase: the processing phase serializes on it.
	"""
	rendered = render_key_expression(
		consumer.ordering_key_expression,
		message.get("payload"),
		message.get("headers"),
		consumer,
	)
	return rendered or dedup_key
