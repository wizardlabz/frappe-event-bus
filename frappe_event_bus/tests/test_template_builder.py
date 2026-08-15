"""Unit tests for the doctype-aware template builder."""

from __future__ import annotations

import datetime
import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus import api
from frappe_event_bus.rendering import render_payload
from frappe_event_bus.template_builder import build_field_tree, classify_field, generate_jinja


class TestClassifyField(unittest.TestCase):
	"""Field classification is pure: a DocField dict in, a decision out."""

	def test_ordinary_field_is_selected_by_default(self):
		out = classify_field({"fieldname": "customer", "fieldtype": "Link", "label": "Customer"})
		self.assertTrue(out["selectable"])
		self.assertTrue(out["default_selected"])
		self.assertIsNone(out["note"])

	def test_password_is_never_selectable(self):
		out = classify_field({"fieldname": "password", "fieldtype": "Password", "label": "Password"})
		self.assertFalse(out["selectable"])
		self.assertFalse(out["default_selected"])
		self.assertIn("never published", out["note"])

	def test_permlevel_field_is_opt_in(self):
		out = classify_field({"fieldname": "cost", "fieldtype": "Currency", "label": "Cost", "permlevel": 1})
		self.assertTrue(out["selectable"])
		self.assertFalse(out["default_selected"])
		self.assertIn("permlevel 1", out["note"])

	def test_internal_fieldname_is_opt_in(self):
		out = classify_field({"fieldname": "amended_from", "fieldtype": "Link", "label": "Amended From"})
		self.assertTrue(out["selectable"])
		self.assertFalse(out["default_selected"])

	def test_attach_is_selected_but_flagged(self):
		out = classify_field({"fieldname": "logo", "fieldtype": "Attach Image", "label": "Logo"})
		self.assertTrue(out["default_selected"])
		self.assertIn("private", out["note"].lower())


class TestBuildFieldTree(FrappeTestCase):
	"""Tree construction reads live meta, so it needs a site."""

	def test_layout_fieldtypes_are_omitted(self):
		tree = build_field_tree("ToDo")
		types = {f["fieldtype"] for f in tree["fields"]}
		self.assertFalse(types & {"Section Break", "Column Break", "Tab Break"})

	def test_real_fields_are_present(self):
		tree = build_field_tree("ToDo")
		self.assertIn("description", {f["fieldname"] for f in tree["fields"]})

	def test_child_tables_are_nested_not_inlined(self):
		tree = build_field_tree("DocType")
		self.assertNotIn("Table", {f["fieldtype"] for f in tree["fields"]})
		children = {c["fieldname"] for c in tree["children"]}
		self.assertIn("fields", children)

	def test_child_table_rows_are_classified_too(self):
		tree = build_field_tree("DocType")
		child = next(c for c in tree["children"] if c["fieldname"] == "fields")
		self.assertIn("fieldname", {f["fieldname"] for f in child["fields"]})
		self.assertTrue(all("default_selected" in f for f in child["fields"]))


class TestGenerateJinja(FrappeTestCase):
	"""Generated Jinja must render to valid JSON for hostile real-world values."""

	def test_envelope_shape(self):
		out = generate_jinja("ToDo", {"fields": ["description"], "children": {}})
		self.assertIn('"event"', out)
		self.assertIn('"data"', out)
		self.assertIn("{{ doc.description | json }}", out)

	def test_never_uses_tojson(self):
		# tojson raises TypeError on Date/Datetime — the filter choice is load-bearing.
		out = generate_jinja("ToDo", {"fields": ["date"], "children": {}})
		self.assertNotIn("tojson", out)

	def test_renders_to_valid_json_for_hostile_values(self):
		out = generate_jinja("ToDo", {"fields": ["description", "date"], "children": {}})
		doc = frappe._dict(
			doctype="ToDo",
			name="TODO-0001",
			description="has \"quotes\", back\\slash,\nnewline, <tag> & 'apos'",
			date=datetime.date(2026, 8, 2),
		)
		rendered = render_payload(out, {"doc": doc, "context": {"event_type": "on_update"}})
		parsed = json.loads(rendered)
		self.assertEqual(parsed["data"]["description"], doc.description)
		self.assertEqual(parsed["data"]["date"], "2026-08-02")

	def test_renders_datetime_and_none(self):
		out = generate_jinja("ToDo", {"fields": ["description", "date"], "children": {}})
		doc = frappe._dict(
			doctype="ToDo",
			name="TODO-0002",
			description=None,
			date=datetime.datetime(2026, 8, 2, 13, 5, 1),
		)
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "after_insert"}}))
		self.assertIsNone(parsed["data"]["description"])
		self.assertTrue(parsed["data"]["date"].startswith("2026-08-02"))

	def test_child_table_rows_render(self):
		out = generate_jinja("DocType", {"fields": ["module"], "children": {"fields": ["fieldname"]}})
		doc = frappe._dict(
			doctype="DocType",
			name="ToDo",
			module="Core",
			fields=[frappe._dict(fieldname="a"), frappe._dict(fieldname='b"quoted')],
		)
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "on_update"}}))
		self.assertEqual([r["fieldname"] for r in parsed["data"]["fields"]], ["a", 'b"quoted'])

	def test_empty_child_table_renders_empty_array(self):
		out = generate_jinja("DocType", {"fields": [], "children": {"fields": ["fieldname"]}})
		doc = frappe._dict(doctype="DocType", name="ToDo", fields=[])
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "on_update"}}))
		self.assertEqual(parsed["data"]["fields"], [])

	def test_empty_selection_still_valid_json(self):
		out = generate_jinja("ToDo", {"fields": [], "children": {}})
		doc = frappe._dict(doctype="ToDo", name="TODO-0003")
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "on_trash"}}))
		self.assertEqual(parsed["data"], {})


class TestBuilderApi(FrappeTestCase):
	"""The picker talks to these two endpoints."""

	def test_get_field_tree_returns_tree(self):
		tree = api.get_field_tree("ToDo")
		self.assertEqual(tree["doctype"], "ToDo")
		self.assertIn("description", {f["fieldname"] for f in tree["fields"]})

	def test_generate_template_accepts_json_string_selection(self):
		out = api.generate_template("ToDo", json.dumps({"fields": ["description"], "children": {}}))
		self.assertIn("{{ doc.description | json }}", out)

	def test_generate_template_accepts_dict_selection(self):
		out = api.generate_template("ToDo", {"fields": ["description"], "children": {}})
		self.assertIn("{{ doc.description | json }}", out)
