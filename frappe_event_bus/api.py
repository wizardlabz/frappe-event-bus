"""Whitelisted API for the Event Bus desk/Vue frontend."""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappe_event_bus.providers.registry import get_provider, get_publisher


@frappe.whitelist()
def test_publish(
	provider: str,
	connection: str,
	destination: str,
	payload: str | dict[str, Any],
	headers: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Publish a one-off test payload via a provider; returns normalized result.

	Args:
		provider: Registered provider name.
		connection: Connection docname.
		destination: Destination docname.
		payload: Test payload (JSON string or dict).
		headers: Optional headers (JSON string or dict).
	"""
	frappe.only_for("System Manager")
	provider_spec = get_provider(provider)
	publisher = get_publisher(provider)
	connection_doc = frappe.get_doc(provider_spec["connection_doctype"], connection)
	destination_doc = frappe.get_doc(provider_spec["destination_doctype"], destination)

	return publisher.test_publish(
		connection_doc,
		destination_doc,
		_as_dict(payload),
		_as_dict(headers) if headers else None,
	)


@frappe.whitelist()
def preview_payload(
	message_template: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict[str, Any]:
	"""Render a message template for the UI preview.

	Uses a real reference document when provided, otherwise the template's
	stored example context.

	Returns:
		The staged report from :func:`render_report` — ``ok``, ``rendered``,
		``json_valid``, ``schema_present``, ``schema_valid``, ``output``,
		``stage`` and ``error`` — so the UI can show which check failed. Also
		carries ``valid`` for backwards compatibility.
	"""
	from frappe_event_bus.rendering import render_report

	template = frappe.get_doc("Event Bus Message Template", message_template)

	if reference_doctype and reference_name:
		ref_doc = frappe.get_doc(reference_doctype, reference_name)
		context = {"doc": ref_doc, "context": {"event_type": "preview"}}
	else:
		context = frappe.parse_json(template.example_context) if template.example_context else {}

	report = render_report(template.jinja_template, context, template.json_schema)
	report["valid"] = report["ok"]
	return report


@frappe.whitelist()
def get_field_tree(doctype: str) -> dict[str, Any]:
	"""Return the two-level picker tree for ``doctype``.

	Args:
		doctype: DocType to introspect.
	"""
	frappe.only_for("System Manager")
	from frappe_event_bus.template_builder import build_field_tree

	return build_field_tree(doctype)


@frappe.whitelist()
def generate_template(doctype: str, selection: str | dict[str, Any]) -> str:
	"""Generate Jinja for ``doctype`` from a picker ``selection``.

	Args:
		doctype: DocType the template targets.
		selection: ``{"fields": [...], "children": {table: [...]}}``, JSON or dict.
	"""
	frappe.only_for("System Manager")
	from frappe_event_bus.template_builder import generate_jinja

	return generate_jinja(doctype, _as_dict(selection))


def _as_dict(value: str | dict[str, Any]) -> dict[str, Any]:
	"""Coerce a JSON string or dict into a dict."""
	if isinstance(value, dict):
		return value
	return frappe.parse_json(value)
