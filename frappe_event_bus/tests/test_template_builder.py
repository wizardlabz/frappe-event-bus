"""Unit tests for the doctype-aware template builder."""

from __future__ import annotations

import unittest

from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.template_builder import build_field_tree, classify_field


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
		out = classify_field(
			{"fieldname": "cost", "fieldtype": "Currency", "label": "Cost", "permlevel": 1}
		)
		self.assertTrue(out["selectable"])
		self.assertFalse(out["default_selected"])
		self.assertIn("permlevel 1", out["note"])

	def test_internal_fieldname_is_opt_in(self):
		out = classify_field(
			{"fieldname": "amended_from", "fieldtype": "Link", "label": "Amended From"}
		)
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
