"""Template-to-doctype binding is optional, but enforced when present."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


def _template(name: str, applies_to: str | None) -> str:
	"""Create (or recreate) a minimal template bound to ``applies_to``."""
	if frappe.db.exists("Event Bus Message Template", name):
		frappe.delete_doc("Event Bus Message Template", name, force=True)
	doc = frappe.get_doc(
		{
			"doctype": "Event Bus Message Template",
			"template_name": name,
			"applies_to_doctype": applies_to,
			"jinja_template": '{"name": {{ doc.name | json }}}',
		}
	).insert()
	return doc.name


def _rule(rule_name: str, reference_doctype: str, template: str) -> frappe.model.document.Document:
	"""Build an unsaved rule linking ``template`` to ``reference_doctype``."""
	if frappe.db.exists("Event Bus Rule", rule_name):
		frappe.delete_doc("Event Bus Rule", rule_name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Event Bus Rule",
			"rule_name": rule_name,
			"reference_doctype": reference_doctype,
			"event_type": "after_insert",
			"message_template": template,
		}
	)


class TestTemplateBinding(FrappeTestCase):
	def test_generic_template_works_with_any_rule(self):
		rule = _rule("eb-rule-generic", "ToDo", _template("eb-generic", None))
		rule.insert()
		self.assertTrue(rule.name)

	def test_matching_binding_is_accepted(self):
		rule = _rule("eb-rule-match", "ToDo", _template("eb-todo", "ToDo"))
		rule.insert()
		self.assertTrue(rule.name)

	def test_mismatched_binding_is_rejected(self):
		rule = _rule("eb-rule-mismatch", "ToDo", _template("eb-note", "Note"))
		with self.assertRaises(frappe.ValidationError):
			rule.insert()
