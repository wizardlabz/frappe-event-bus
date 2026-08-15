"""Whitelisted API for the Event Bus desk/Vue frontend.

Every endpoint here authorizes its own caller. ``@frappe.whitelist()`` exposes a
function over ``/api/method/...`` to any authenticated user regardless of what
the desk chooses to render, so hiding a button is not access control.

Authorization goes through ``frappe.has_permission`` against the doctype each
endpoint actually touches, rather than a hardcoded role. That keeps a site's own
permission model authoritative — grant a custom role access to the Event Bus
doctypes and the API follows — and, unlike ``frappe.only_for``, it is still
enforced under ``frappe.flags.in_test`` so the checks can be tested.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from frappe_event_bus.providers.registry import get_provider, get_publisher

TEMPLATE_DOCTYPE = "Event Bus Message Template"


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
	provider_spec = get_provider(provider)
	# Test publishing opens a real broker connection and sends a real message,
	# so require read access to the connection and destination being used.
	frappe.has_permission(provider_spec["connection_doctype"], "read", doc=connection, throw=True)
	frappe.has_permission(provider_spec["destination_doctype"], "read", doc=destination, throw=True)

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

	frappe.has_permission(TEMPLATE_DOCTYPE, "read", doc=message_template, throw=True)
	template = frappe.get_doc(TEMPLATE_DOCTYPE, message_template)

	if reference_doctype and reference_name:
		# Both come from the caller and the rendered payload is returned to
		# them, so previewing a document must require permission to read it.
		# Access to the template grants no access to the data it renders.
		frappe.has_permission(reference_doctype, "read", doc=reference_name, throw=True)
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
	frappe.has_permission(TEMPLATE_DOCTYPE, "write", throw=True)
	from frappe_event_bus.template_builder import build_field_tree

	return build_field_tree(doctype)


@frappe.whitelist()
def generate_template(doctype: str, selection: str | dict[str, Any]) -> str:
	"""Generate Jinja for ``doctype`` from a picker ``selection``.

	Args:
		doctype: DocType the template targets.
		selection: ``{"fields": [...], "children": {table: [...]}}``, JSON or dict.
	"""
	frappe.has_permission(TEMPLATE_DOCTYPE, "write", throw=True)
	from frappe_event_bus.template_builder import generate_jinja

	return generate_jinja(doctype, _as_dict(selection))


def _as_dict(value: str | dict[str, Any]) -> dict[str, Any]:
	"""Coerce a JSON string or dict into a dict."""
	if isinstance(value, dict):
		return value
	return frappe.parse_json(value)
