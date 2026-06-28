"""Pure payload rendering and lightweight JSON Schema validation.

These functions are intentionally free of doctype/DB coupling so they can be
unit tested directly. ``render_payload`` renders a Jinja template (via
``frappe.render_template``) into a JSON string, validates it parses as JSON, and
optionally validates it against a minimal JSON Schema subset.

The schema validator supports a practical subset of JSON Schema: ``type``
(object/array/string/number/integer/boolean/null), ``required`` and nested
``properties``. It deliberately avoids adding a third-party dependency.
"""

from __future__ import annotations

import json
from typing import Any

import frappe


class TemplateRenderError(frappe.ValidationError):
	"""Raised when a template fails to render or produces invalid JSON."""


class SchemaValidationError(frappe.ValidationError):
	"""Raised when a rendered payload fails JSON Schema validation."""


_TYPE_MAP: dict[str, tuple[type, ...]] = {
	"object": (dict,),
	"array": (list,),
	"string": (str,),
	"number": (int, float),
	"integer": (int,),
	"boolean": (bool,),
	"null": (type(None),),
}


def render_payload(
	template: str,
	context: dict[str, Any],
	json_schema: str | None = None,
) -> str:
	"""Render ``template`` with ``context`` into a validated JSON string.

	Args:
		template: Jinja template producing a JSON document.
		context: Render context (typically ``{"doc": ..., "context": ...}``).
		json_schema: Optional JSON Schema (as a JSON string) to validate against.

	Returns:
		The rendered JSON string.

	Raises:
		TemplateRenderError: If rendering fails or the result is not valid JSON.
		SchemaValidationError: If the payload violates ``json_schema``.
	"""
	try:
		rendered = frappe.render_template(template, context)
	except Exception as exc:  # noqa: BLE001 - jinja raises many error types
		raise TemplateRenderError(frappe._("Failed to render template: {0}").format(exc)) from exc

	try:
		parsed = json.loads(rendered)
	except json.JSONDecodeError as exc:
		raise TemplateRenderError(
			frappe._("Rendered payload is not valid JSON: {0}").format(exc)
		) from exc

	if json_schema:
		schema = json_schema if isinstance(json_schema, dict) else json.loads(json_schema)
		validate_against_schema(parsed, schema)

	return rendered


def validate_against_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
	"""Validate ``value`` against a minimal JSON Schema subset.

	Raises:
		SchemaValidationError: On the first validation failure.
	"""
	expected_type = schema.get("type")
	if expected_type:
		_check_type(value, expected_type, path)

	if expected_type == "object" or isinstance(value, dict):
		for required in schema.get("required", []):
			if not isinstance(value, dict) or required not in value:
				raise SchemaValidationError(
					frappe._("Missing required property '{0}' at {1}").format(required, path)
				)
		properties = schema.get("properties") or {}
		if isinstance(value, dict):
			for key, subschema in properties.items():
				if key in value:
					validate_against_schema(value[key], subschema, f"{path}.{key}")


def _check_type(value: Any, expected_type: str, path: str) -> None:
	"""Raise if ``value`` is not of ``expected_type`` (bool excluded from numbers)."""
	allowed = _TYPE_MAP.get(expected_type)
	if allowed is None:
		return
	# bool is a subclass of int; exclude it from number/integer checks.
	if expected_type in ("number", "integer") and isinstance(value, bool):
		raise SchemaValidationError(
			frappe._("Expected {0} at {1}, got boolean").format(expected_type, path)
		)
	if not isinstance(value, allowed):
		raise SchemaValidationError(
			frappe._("Expected {0} at {1}, got {2}").format(expected_type, path, type(value).__name__)
		)
