"""Outbox worker: publishes Pending / due Retry Scheduled messages.

Selects due rows and, for each, records a Delivery Attempt and drives the status
machine based on the provider's normalized result.
"""

from __future__ import annotations

import json
import time
from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

from frappe_event_bus.frappe_event_bus.doctype.event_bus_settings.event_bus_settings import (
	get_settings,
)
from frappe_event_bus.providers.registry import get_publisher
from frappe_event_bus.publisher.backoff import compute_backoff_seconds

DUE_STATUSES = ("Pending", "Retry Scheduled")


def process_pending(batch_size: int | None = None) -> dict[str, int]:
	"""Process a batch of due outbox messages.

	Args:
		batch_size: Max rows to process; defaults to the configured worker batch size.

	Returns:
		Counts dict: ``{"processed", "published", "failed", "retried"}``.
	"""
	settings = get_settings()
	limit = batch_size or settings.worker_batch_size or 50

	names = _select_due_messages(limit)
	counts = {"processed": 0, "published": 0, "failed": 0, "retried": 0}
	for name in names:
		# Isolate each message: an unexpected failure (e.g. a DB error) rolls back
		# only this message via a savepoint, so the rest of the batch still commits.
		frappe.db.savepoint("eb_outbox_msg")
		try:
			outcome = process_message(name)
		except Exception:
			frappe.db.rollback(save_point="eb_outbox_msg")
			frappe.log_error(
				title="Event Bus: process_message failed",
				message=frappe.get_traceback(),
			)
			outcome = "failed"
		counts["processed"] += 1
		if outcome in counts:
			counts[outcome] += 1
	return counts


def _select_due_messages(limit: int) -> list[str]:
	"""Return names of Pending or due Retry Scheduled outbox messages."""
	now = now_datetime()
	rows = frappe.get_all(
		"Event Bus Outbox Message",
		filters=[
			["status", "in", list(DUE_STATUSES)],
		],
		or_filters=[
			["status", "=", "Pending"],
			["next_retry_at", "<=", now],
		],
		order_by="creation asc",
		limit=limit,
		pluck="name",
	)
	return rows


def _claim_message(name: str) -> bool:
	"""Atomically claim a due message by flipping it to ``Publishing``.

	A single conditional UPDATE is the claim: only the worker whose UPDATE actually
	changes the row (status was still ``Pending``/``Retry Scheduled``) wins. The
	row lock blocks concurrent claimers until this worker's transaction ends; they
	then see ``Publishing`` and lose. This prevents double-delivery when the
	post-commit enqueue job and the cron worker run at the same time.

	Args:
		name: Outbox Message docname.

	Returns:
		True if this worker claimed the row, False if another worker already had it.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabEvent Bus Outbox Message`
		SET status = 'Publishing'
		WHERE name = %s AND status IN ('Pending', 'Retry Scheduled')
		""",
		name,
	)
	return frappe.db._cursor.rowcount == 1


def build_message(outbox: Any) -> dict[str, Any]:
	"""Build the normalized message dict passed to ``provider.publish``."""
	return {
		"outbox_name": outbox.name,
		"provider": outbox.provider,
		"connection": outbox.connection,
		"destination": outbox.destination,
		"routing_key": outbox.routing_key,
		"payload": frappe.parse_json(outbox.payload) if outbox.payload else {},
		"payload_json": outbox.payload or "{}",
		"headers": frappe.parse_json(outbox.headers) if outbox.headers else {},
		"reference_doctype": outbox.reference_doctype,
		"reference_name": outbox.reference_document,
		"event_type": outbox.event_type,
		"deduplication_key": outbox.deduplication_key,
	}


def process_message(name: str) -> str:
	"""Publish a single outbox message and advance its status.

	Returns:
		One of ``"published"``, ``"retried"`` or ``"failed"``.
	"""
	settings = get_settings()
	if not _claim_message(name):
		# Another worker already claimed this row; skip to avoid double-delivery.
		return "skipped"

	outbox = frappe.get_doc("Event Bus Outbox Message", name)
	attempt_number = (outbox.attempt_count or 0) + 1

	message = build_message(outbox)
	started = now_datetime()
	start_perf = time.monotonic()

	result = _safe_publish(outbox.provider, message)

	duration_ms = int((time.monotonic() - start_perf) * 1000)
	if settings.enable_delivery_logging:
		_record_attempt(outbox, attempt_number, started, duration_ms, result)

	return _apply_result(outbox, attempt_number, settings, result)


def _safe_publish(provider: str, message: dict[str, Any]) -> dict[str, Any]:
	"""Invoke the provider publisher, converting exceptions into failures."""
	try:
		return get_publisher(provider).publish(message)
	except Exception as exc:
		frappe.log_error(
			title="Event Bus: provider publish raised",
			message=frappe.get_traceback(),
		)
		return {"success": False, "error": str(exc), "retryable": True}


def _apply_result(
	outbox: Any,
	attempt_number: int,
	settings: Any,
	result: dict[str, Any],
) -> str:
	"""Update the outbox row from a normalized publish result; return outcome."""
	outbox.attempt_count = attempt_number

	if result.get("success"):
		outbox.status = "Published"
		outbox.published_at = now_datetime()
		outbox.last_error = None
		outbox.save(ignore_permissions=True)
		return "published"

	error = result.get("error") or "Unknown error"
	retryable = result.get("retryable", True)
	max_attempts = settings.max_publish_attempts or 5
	outbox.last_error = error

	if retryable and attempt_number < max_attempts:
		delay = compute_backoff_seconds(attempt_number, settings.retry_backoff_seconds or 60)
		outbox.status = "Retry Scheduled"
		outbox.next_retry_at = add_to_date(now_datetime(), seconds=delay)
		outbox.save(ignore_permissions=True)
		return "retried"

	# Exhausted retries -> Failed; explicitly non-retryable -> Dead Lettered.
	outbox.status = "Failed" if retryable else "Dead Lettered"
	outbox.save(ignore_permissions=True)
	return "failed"


def _record_attempt(
	outbox: Any,
	attempt_number: int,
	started: Any,
	duration_ms: int,
	result: dict[str, Any],
) -> None:
	"""Persist a Delivery Attempt row for this publish attempt."""
	success = bool(result.get("success"))
	frappe.get_doc(
		{
			"doctype": "Event Bus Delivery Attempt",
			"outbox_message": outbox.name,
			"attempt_number": attempt_number,
			"provider": outbox.provider,
			"started_at": started,
			"completed_at": now_datetime(),
			"success": success,
			"error_message": None if success else (result.get("error") or "Unknown error"),
			"provider_response": json.dumps(result.get("response") or result),
			"duration_ms": duration_ms,
		}
	).insert(ignore_permissions=True)
