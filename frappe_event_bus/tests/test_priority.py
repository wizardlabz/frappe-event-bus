"""Destination priority orders outbox processing.

Priority is ascending: a lower number is published first. It is carried from
the rule's destination row onto the outbox message so the worker can order by
it, because ordering only at creation time would be defeated by rows sharing a
creation timestamp inside one transaction.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.publisher.outbox_worker import _select_due_messages

TEMPLATE = "eb-prio-template"
RULE = "eb-prio-rule"


def _cleanup():
	for dt, name in (("Event Bus Rule", RULE), ("Event Bus Message Template", TEMPLATE)):
		if frappe.db.exists(dt, name):
			frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
	frappe.db.delete("Event Bus Outbox Message", {"event_rule": RULE})


class TestDestinationPriority(FrappeTestCase):
	def setUp(self):
		_cleanup()
		frappe.get_doc(
			{
				"doctype": "Event Bus Message Template",
				"template_name": TEMPLATE,
				"jinja_template": '{"n": {{ doc.name | json }}}',
			}
		).insert()

	def tearDown(self):
		_cleanup()

	def _rule_with_priorities(self, priorities: list[int]):
		return frappe.get_doc(
			{
				"doctype": "Event Bus Rule",
				"rule_name": RULE,
				"enabled": 1,
				"reference_doctype": "ToDo",
				"event_type": "after_insert",
				"message_template": TEMPLATE,
				"destinations": [
					{
						"enabled": 1,
						"provider": "fake",
						"connection": "c",
						"destination": f"d{p}",
						"priority": p,
					}
					for p in priorities
				],
			}
		).insert()

	def test_priority_is_copied_onto_the_outbox_message(self):
		self._rule_with_priorities([5, 1])
		todo = frappe.get_doc({"doctype": "ToDo", "description": "prio"}).insert()
		rows = frappe.get_all(
			"Event Bus Outbox Message",
			filters={"reference_document": todo.name},
			fields=["destination", "priority"],
		)
		self.assertEqual({r.destination: r.priority for r in rows}, {"d5": 5, "d1": 1})

	def test_worker_selects_lower_priority_number_first(self):
		self._rule_with_priorities([9, 2, 5])
		todo = frappe.get_doc({"doctype": "ToDo", "description": "prio-order"}).insert()
		# No commit: FrappeTestCase rolls each test back, and committing here
		# would escape that, leaking an enabled ToDo rule into later tests.
		selected = _select_due_messages(50)
		mine = frappe.get_all(
			"Event Bus Outbox Message",
			filters={"reference_document": todo.name},
			fields=["name", "priority"],
		)
		by_name = {r.name: r.priority for r in mine}
		ordered = [by_name[n] for n in selected if n in by_name]
		self.assertEqual(ordered, [2, 5, 9])

	def test_missing_priority_defaults_to_zero(self):
		frappe.get_doc(
			{
				"doctype": "Event Bus Rule",
				"rule_name": RULE,
				"enabled": 1,
				"reference_doctype": "ToDo",
				"event_type": "after_insert",
				"message_template": TEMPLATE,
				"destinations": [
					{"enabled": 1, "provider": "fake", "connection": "c", "destination": "d"}
				],
			}
		).insert()
		todo = frappe.get_doc({"doctype": "ToDo", "description": "no-prio"}).insert()
		row = frappe.get_all(
			"Event Bus Outbox Message",
			filters={"reference_document": todo.name},
			fields=["priority"],
		)[0]
		self.assertEqual(row.priority, 0)
