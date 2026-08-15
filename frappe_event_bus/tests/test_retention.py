"""Retention deletes old succeeded outbox messages and their attempts.

Failures are deliberately kept: the point of retention is to stop the outbox
growing without bound, not to destroy the evidence you need to debug a
delivery problem.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from frappe_event_bus.publisher.retention import purge_old_messages

RULE = "eb-retention-rule"


def _ensure_rule() -> None:
	"""Outbox rows link to a rule, so retention fixtures need a real one."""
	if frappe.db.exists("Event Bus Rule", RULE):
		return
	if not frappe.db.exists("Event Bus Message Template", "eb-retention-template"):
		frappe.get_doc(
			{
				"doctype": "Event Bus Message Template",
				"template_name": "eb-retention-template",
				"jinja_template": '{"n": {{ doc.name | json }}}',
			}
		).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Event Bus Rule",
			"rule_name": RULE,
			"enabled": 0,
			"reference_doctype": "Note",
			"event_type": "after_insert",
			"message_template": "eb-retention-template",
		}
	).insert(ignore_permissions=True)


def _make_outbox(status: str, age_days: int) -> str:
	_ensure_rule()
	doc = frappe.get_doc(
		{
			"doctype": "Event Bus Outbox Message",
			"event_rule": RULE,
			"provider": "fake",
			"connection": "c",
			"destination": "d",
			"reference_doctype": "ToDo",
			"reference_document": "x",
			"event_type": "after_insert",
			"payload": "{}",
			"status": status,
			"attempt_count": 1,
		}
	).insert(ignore_permissions=True)
	old = add_days(now_datetime(), -age_days)
	# creation is set by the framework; retention reads modified.
	frappe.db.set_value("Event Bus Outbox Message", doc.name, "modified", old, update_modified=False)
	return doc.name


def _attempt_for(outbox: str) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Event Bus Delivery Attempt",
				"outbox_message": outbox,
				"attempt_number": 1,
				"provider": "fake",
				"success": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _set_retention(days):
	settings = frappe.get_single("Event Bus Settings")
	settings.retention_days = days
	settings.save()
	frappe.db.commit()


class TestRetention(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Event Bus Delivery Attempt", {"provider": "fake"})
		frappe.db.delete("Event Bus Outbox Message", {"event_rule": RULE})
		_set_retention(0)

	def test_old_published_message_is_purged(self):
		name = _make_outbox("Published", 40)
		_set_retention(30)
		purge_old_messages()
		self.assertFalse(frappe.db.exists("Event Bus Outbox Message", name))

	def test_recent_published_message_is_kept(self):
		name = _make_outbox("Published", 5)
		_set_retention(30)
		purge_old_messages()
		self.assertTrue(frappe.db.exists("Event Bus Outbox Message", name))

	def test_old_failures_are_kept_for_forensics(self):
		for status in ("Failed", "Dead Lettered", "Retry Scheduled"):
			name = _make_outbox(status, 90)
			_set_retention(30)
			purge_old_messages()
			self.assertTrue(
				frappe.db.exists("Event Bus Outbox Message", name),
				f"{status} should survive retention",
			)

	def test_delivery_attempts_are_purged_with_their_message(self):
		name = _make_outbox("Published", 40)
		attempt = _attempt_for(name)
		_set_retention(30)
		purge_old_messages()
		self.assertFalse(frappe.db.exists("Event Bus Delivery Attempt", attempt))

	def test_zero_retention_disables_purging(self):
		name = _make_outbox("Published", 999)
		_set_retention(0)
		purge_old_messages()
		self.assertTrue(frappe.db.exists("Event Bus Outbox Message", name))

	def test_purge_reports_what_it_deleted(self):
		_make_outbox("Published", 40)
		_make_outbox("Published", 40)
		_set_retention(30)
		result = purge_old_messages()
		self.assertEqual(result["messages"], 2)
