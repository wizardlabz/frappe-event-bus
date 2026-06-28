"""Rule engine: turns document events into Outbox Message rows.

Wired via a generic ``doc_events`` hook on ``"*"``. ``handle_event`` is the single
entry point. It must never raise into the host document's transaction; any
failure is logged and swallowed.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.model.document import Document

from frappe_event_bus.frappe_event_bus.doctype.event_bus_settings.event_bus_settings import (
	get_settings,
)

EVENT_TYPES = ("after_insert", "on_update", "on_submit", "on_cancel", "on_trash")


def evaluate_condition(condition: str | None, doc: Document) -> bool:
	"""Evaluate a rule condition safely. Empty/blank conditions match.

	Args:
		condition: Python expression evaluated with ``{"doc": doc}``.
		doc: The document being processed.

	Returns:
		True if the rule matches.
	"""
	if not condition or not condition.strip():
		return True
	result = frappe.safe_eval(condition, get_safe_eval_globals(), {"doc": doc})
	return bool(result)


def get_safe_eval_globals() -> dict[str, Any]:
	"""Return the globals exposed to condition expressions."""
	return {"frappe": frappe._dict(utils=frappe.utils)}


def handle_event(doc: Document, event_type: str) -> None:
	"""Entry point invoked by the generic ``doc_events`` hook.

	Finds matching enabled rules and enqueues Outbox Messages. Never raises.
	"""
	try:
		_handle_event(doc, event_type)
	except Exception:  # noqa: BLE001 - must not break the host transaction
		frappe.log_error(
			title="Event Bus: handle_event failed",
			message=frappe.get_traceback(),
		)


def _handle_event(doc: Document, event_type: str) -> None:
	"""Inner implementation of :func:`handle_event` (may raise)."""
	if _is_internal_doctype(doc.doctype):
		return

	settings = get_settings()
	if not settings.enabled:
		return

	rules = frappe.get_all(
		"Event Bus Rule",
		filters={"enabled": 1, "reference_doctype": doc.doctype, "event_type": event_type},
		pluck="name",
	)
	if not rules:
		return

	created_any = False
	for rule_name in rules:
		created_any |= _process_rule(rule_name, doc, event_type)

	if created_any:
		_enqueue_worker()


def _process_rule(rule_name: str, doc: Document, event_type: str) -> bool:
	"""Process a single rule; returns True if any outbox row was created."""
	rule = frappe.get_cached_doc("Event Bus Rule", rule_name)
	if not evaluate_condition(rule.condition, doc):
		return False

	context = {"doc": doc, "context": {"event_type": event_type}}
	template = frappe.get_cached_doc("Event Bus Message Template", rule.message_template)
	payload_json = template.render(context)
	dedup_key = _render_dedup_key(rule.deduplication_key_template, context)

	created = False
	for destination in rule.destinations:
		if not destination.enabled:
			continue
		_create_outbox_message(rule, destination, doc, event_type, payload_json, dedup_key, context)
		created = True
	return created


def _create_outbox_message(
	rule: Document,
	destination: Document,
	doc: Document,
	event_type: str,
	payload_json: str,
	dedup_key: str | None,
	context: dict[str, Any],
) -> None:
	"""Insert a single Pending Outbox Message for a destination."""
	headers = _render_headers(destination.headers_template, context)
	outbox = frappe.get_doc(
		{
			"doctype": "Event Bus Outbox Message",
			"event_rule": rule.name,
			"message_template": rule.message_template,
			"provider": destination.provider,
			"connection": destination.connection,
			"destination": destination.destination,
			"routing_key": destination.routing_key,
			"reference_doctype": doc.doctype,
			"reference_document": doc.name,
			"event_type": event_type,
			"payload": payload_json,
			"headers": json.dumps(headers),
			"deduplication_key": dedup_key,
			"status": "Pending",
			"attempt_count": 0,
		}
	)
	outbox.insert(ignore_permissions=True)


def _render_dedup_key(template: str | None, context: dict[str, Any]) -> str | None:
	"""Render the deduplication key template, if any."""
	if not template or not template.strip():
		return None
	return frappe.render_template(template, context).strip()


def _render_headers(template: str | None, context: dict[str, Any]) -> dict[str, Any]:
	"""Render a headers Jinja template into a dict (empty on blank/invalid)."""
	if not template or not template.strip():
		return {}
	rendered = frappe.render_template(template, context)
	try:
		parsed = json.loads(rendered)
	except json.JSONDecodeError:
		frappe.log_error(
			title="Event Bus: invalid headers template",
			message=f"Rendered headers were not valid JSON:\n{rendered}",
		)
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _enqueue_worker() -> None:
	"""Enqueue the outbox worker to run after the host transaction commits."""
	frappe.enqueue(
		"frappe_event_bus.publisher.outbox_worker.process_pending",
		queue="default",
		enqueue_after_commit=True,
	)


def _is_internal_doctype(doctype: str) -> bool:
	"""Skip the event bus's own doctypes to avoid recursion/noise."""
	return doctype in {
		"Event Bus Outbox Message",
		"Event Bus Delivery Attempt",
		"Event Bus Rule",
		"Event Bus Rule Destination",
		"Event Bus Message Template",
		"Event Bus Settings",
	}
