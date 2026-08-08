"""Unit tests for pure payload rendering and schema validation."""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.rendering import (
	SchemaValidationError,
	TemplateRenderError,
	render_payload,
	render_report,
	validate_against_schema,
)


class TestRenderPayload(unittest.TestCase):
	def test_renders_valid_json(self) -> None:
		template = '{"id": "{{ doc.name }}", "total": {{ doc.total }}}'
		out = render_payload(template, {"doc": {"name": "SO-001", "total": 42}})
		self.assertEqual(out, '{"id": "SO-001", "total": 42}')

	def test_invalid_json_raises(self) -> None:
		template = '{"id": {{ doc.name }}}'  # unquoted string -> invalid JSON
		with self.assertRaises(TemplateRenderError):
			render_payload(template, {"doc": {"name": "SO-001"}})

	def test_schema_validation_passes(self) -> None:
		schema = '{"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}'
		template = '{"id": "{{ doc.name }}"}'
		out = render_payload(template, {"doc": {"name": "X"}}, json_schema=schema)
		self.assertEqual(out, '{"id": "X"}')

	def test_schema_validation_fails_missing_required(self) -> None:
		schema = '{"type": "object", "required": ["id"]}'
		template = '{"other": 1}'
		with self.assertRaises(SchemaValidationError):
			render_payload(template, {}, json_schema=schema)

	def test_schema_validation_fails_wrong_type(self) -> None:
		schema = '{"type": "object", "properties": {"id": {"type": "string"}}}'
		template = '{"id": 5}'
		with self.assertRaises(SchemaValidationError):
			render_payload(template, {}, json_schema=schema)


class TestValidateAgainstSchema(unittest.TestCase):
	def test_array_type(self) -> None:
		validate_against_schema([1, 2], {"type": "array"})  # no raise

	def test_integer_rejects_bool(self) -> None:
		with self.assertRaises(SchemaValidationError):
			validate_against_schema(True, {"type": "integer"})

	def test_nested_properties(self) -> None:
		schema = {
			"type": "object",
			"properties": {"meta": {"type": "object", "required": ["v"]}},
		}
		with self.assertRaises(SchemaValidationError):
			validate_against_schema({"meta": {}}, schema)


if __name__ == "__main__":
	unittest.main()


class TestRenderReport(FrappeTestCase):
	"""``render_report`` reports each stage instead of raising.

	The preview UI needs to say *which* check failed — a template that renders
	but breaks its schema is a different problem from one that will not render
	at all — so the staged report is the shared path and ``render_payload``
	raises on top of it.
	"""

	def test_clean_render_with_no_schema(self):
		r = render_report('{"a": {{ doc.x | json }}}', {"doc": frappe._dict(x=1)})
		self.assertTrue(r["ok"])
		self.assertTrue(r["rendered"])
		self.assertTrue(r["json_valid"])
		self.assertFalse(r["schema_present"])
		self.assertIsNone(r["schema_valid"])
		self.assertIsNone(r["stage"])

	def test_render_failure_is_reported_not_raised(self):
		r = render_report("{{ doc.x.__class__ }}", {"doc": frappe._dict(x=1)})
		self.assertFalse(r["ok"])
		self.assertFalse(r["rendered"])
		self.assertEqual(r["stage"], "render")
		self.assertTrue(r["error"])

	def test_invalid_json_is_reported_with_the_offending_output(self):
		r = render_report('{"a": "{{ doc.x }}"', {"doc": frappe._dict(x=1)})
		self.assertFalse(r["ok"])
		self.assertTrue(r["rendered"])
		self.assertFalse(r["json_valid"])
		self.assertEqual(r["stage"], "json")
		# The raw output is still returned so the user can see what broke.
		self.assertIn('"a"', r["output"])

	def test_schema_pass_is_reported(self):
		schema = '{"type": "object", "required": ["a"]}'
		r = render_report('{"a": 1}', {}, schema)
		self.assertTrue(r["ok"])
		self.assertTrue(r["schema_present"])
		self.assertTrue(r["schema_valid"])

	def test_schema_failure_is_distinct_from_json_failure(self):
		schema = '{"type": "object", "required": ["missing"]}'
		r = render_report('{"a": 1}', {}, schema)
		self.assertFalse(r["ok"])
		self.assertTrue(r["json_valid"])   # the payload itself is fine
		self.assertFalse(r["schema_valid"])
		self.assertEqual(r["stage"], "schema")
		self.assertIn("missing", r["error"])

	def test_render_payload_still_raises_on_top_of_the_report(self):
		with self.assertRaises(TemplateRenderError):
			render_payload('{"a": "{{ doc.x }}"', {"doc": frappe._dict(x=1)})
		with self.assertRaises(SchemaValidationError):
			render_payload('{"a": 1}', {}, '{"type": "object", "required": ["missing"]}')
