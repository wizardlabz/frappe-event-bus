"""Unit tests for pure payload rendering and schema validation."""

import unittest

import frappe

from frappe_event_bus.rendering import (
	SchemaValidationError,
	TemplateRenderError,
	render_payload,
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
