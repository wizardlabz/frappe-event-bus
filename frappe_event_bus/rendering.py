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


class SchemaDocumentError(SchemaValidationError):
	"""Raised when the schema itself is malformed, rather than the payload.

	Subclasses :class:`SchemaValidationError` so existing callers that catch
	schema problems keep working, while the preview can tell the two apart.
	"""


_TYPE_MAP: dict[str, tuple[type, ...]] = {
	"object": (dict,),
	"array": (list,),
	"string": (str,),
	"number": (int, float),
	"integer": (int,),
	"boolean": (bool,),
	"null": (type(None),),
}


def validate_schema_document(schema: Any, path: str = "$") -> None:
	"""Check that ``schema`` is a schema this validator can actually enforce.

	Only the subset documented for :func:`validate_against_schema` is accepted.
	An unrecognised ``type`` is rejected rather than ignored: silently skipping
	it would leave a schema that validates nothing while appearing to pass.

	Raises:
		SchemaDocumentError: On the first structural problem found.
	"""
	if not isinstance(schema, dict):
		raise SchemaDocumentError(
			frappe._("Schema at {0} must be an object, got {1}").format(
				path, type(schema).__name__
			)
		)

	declared_type = schema.get("type")
	if declared_type is not None and (
		not isinstance(declared_type, str) or declared_type not in _TYPE_MAP
	):
		raise SchemaDocumentError(
			frappe._("Unknown type '{0}' at {1}. Supported types: {2}").format(
				declared_type, path, ", ".join(sorted(_TYPE_MAP))
			)
		)

	required = schema.get("required")
	if required is not None and (
		not isinstance(required, list) or not all(isinstance(key, str) for key in required)
	):
		raise SchemaDocumentError(
			frappe._("'required' at {0} must be a list of property names").format(path)
		)

	properties = schema.get("properties")
	if properties is not None:
		if not isinstance(properties, dict):
			raise SchemaDocumentError(
				frappe._("'properties' at {0} must be an object").format(path)
			)
		for key, subschema in properties.items():
			validate_schema_document(subschema, f"{path}.{key}")


def render_report(
	template: str,
	context: dict[str, Any],
	json_schema: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Render and validate, reporting each stage instead of raising.

	Rendering has three distinct failure modes and the UI needs to tell them
	apart: a template that will not render, one that renders to text that is
	not JSON, and one that produces perfectly good JSON violating its schema.
	Collapsing them into a single error loses the information that tells you
	what to fix.

	Args:
		template: Jinja template producing a JSON document.
		context: Render context (typically ``{"doc": ..., "context": ...}``).
		json_schema: Optional JSON Schema, as a JSON string or a dict.

	Returns:
		Dict with ``ok``, ``rendered``, ``json_valid``, ``schema_present``,
		``schema_parsed`` (whether the schema itself is usable), ``schema_valid``
		(``None`` when there is no schema, or when the schema was too broken to
		check against), ``output``, ``parsed``, the failing ``stage`` — one of
		``render``, ``json``, ``schema_invalid``, ``schema`` — and a
		human-readable ``error``.
	"""
	report: dict[str, Any] = {
		"ok": False,
		"rendered": False,
		"json_valid": False,
		"schema_present": bool(json_schema),
		"schema_parsed": None,
		"schema_valid": None,
		"output": "",
		"parsed": None,
		"stage": None,
		"error": None,
	}

	try:
		report["output"] = frappe.render_template(template, context)
	except Exception as exc:
		report["stage"] = "render"
		report["error"] = frappe._("Failed to render template: {0}").format(exc)
		return report
	report["rendered"] = True

	try:
		report["parsed"] = json.loads(report["output"])
	except json.JSONDecodeError as exc:
		report["stage"] = "json"
		report["error"] = frappe._("Rendered payload is not valid JSON: {0}").format(exc)
		return report
	report["json_valid"] = True

	if not json_schema:
		report["ok"] = True
		return report

	try:
		schema = json_schema if isinstance(json_schema, dict) else json.loads(json_schema)
	except json.JSONDecodeError as exc:
		report["stage"] = "schema_invalid"
		report["schema_parsed"] = False
		report["error"] = frappe._("JSON Schema is not valid JSON: {0}").format(exc)
		return report

	try:
		validate_schema_document(schema)
	except SchemaDocumentError as exc:
		report["stage"] = "schema_invalid"
		report["schema_parsed"] = False
		report["error"] = str(exc)
		return report
	report["schema_parsed"] = True

	try:
		validate_against_schema(report["parsed"], schema)
	except SchemaValidationError as exc:
		report["stage"] = "schema"
		report["schema_valid"] = False
		report["error"] = str(exc)
		return report

	report["schema_valid"] = True
	report["ok"] = True
	return report


def render_payload(
	template: str,
	context: dict[str, Any],
	json_schema: str | None = None,
) -> str:
	"""Render ``template`` with ``context`` into a validated JSON string.

	The raising counterpart of :func:`render_report`, used on the publish path
	where a bad payload must stop the message rather than be reported.

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
	report = render_report(template, context, json_schema)

	if report["stage"] in ("render", "json"):
		raise TemplateRenderError(report["error"])
	if report["stage"] == "schema_invalid":
		raise SchemaDocumentError(report["error"])
	if report["stage"] == "schema":
		raise SchemaValidationError(report["error"])

	return report["output"]


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
		raise SchemaValidationError(frappe._("Expected {0} at {1}, got boolean").format(expected_type, path))
	if not isinstance(value, allowed):
		raise SchemaValidationError(
			frappe._("Expected {0} at {1}, got {2}").format(expected_type, path, type(value).__name__)
		)
