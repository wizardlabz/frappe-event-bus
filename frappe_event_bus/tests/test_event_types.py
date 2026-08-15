"""Every hooked document event reaches the outbox.

``hooks.py`` wires all five lifecycle events, but only ``after_insert`` was
ever exercised — so a regression in submit/cancel/trash handling would have
gone unnoticed. These tests drive a real document through its whole lifecycle
and assert which rules fire at each step.

Driving ``on_submit``/``on_cancel`` needs a submittable DocType, and Frappe
core ships none — the only submittable doctypes on a bench come from ERPNext,
which this app does not depend on and CI does not install. So the fixture
below creates its own: a custom, submittable DocType with no mandatory fields,
built once per class and dropped afterwards.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.tests.fake_provider import register_fake_provider

TEST_DOCTYPE = "_Test EB Lifecycle Doc"
TEMPLATE = "_Test EB Lifecycle Template"
EVENT_TYPES = ("after_insert", "on_update", "on_submit", "on_cancel", "on_trash")


def _ensure_test_doctype() -> None:
	"""Create the submittable fixture DocType if it is not already present.

	``custom=1`` keeps this in the database only — no files are written and
	developer mode is not required. Creating a DocType is DDL, which commits
	implicitly and therefore escapes the per-test rollback, so this runs once
	per class and is torn down explicitly by :func:`_drop_test_doctype`.
	"""
	if frappe.db.exists("DocType", TEST_DOCTYPE):
		return

	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TEST_DOCTYPE,
			"module": "Frappe Event Bus",
			"custom": 1,
			"is_submittable": 1,
			"autoname": "hash",
			"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
			"permissions": [
				{
					"role": "System Manager",
					"read": 1,
					"write": 1,
					"create": 1,
					"delete": 1,
					"submit": 1,
					"cancel": 1,
					"amend": 1,
				}
			],
		}
	).insert(ignore_permissions=True)


def _drop_test_doctype() -> None:
	"""Remove the fixture DocType and its table."""
	if not frappe.db.exists("DocType", TEST_DOCTYPE):
		return
	frappe.db.delete(TEST_DOCTYPE)
	frappe.delete_doc("DocType", TEST_DOCTYPE, force=1, ignore_permissions=True)


def _rule_name(event_type: str) -> str:
	return f"_Test EB Lifecycle {event_type}"


def _cleanup() -> None:
	for event_type in EVENT_TYPES:
		frappe.db.delete("Event Bus Outbox Message", {"event_rule": _rule_name(event_type)})
		frappe.delete_doc_if_exists("Event Bus Rule", _rule_name(event_type), force=1)
	frappe.delete_doc_if_exists("Event Bus Message Template", TEMPLATE, force=1)


def _setup_rules(event_types: tuple[str, ...] = EVENT_TYPES) -> None:
	"""One enabled rule per event type, all pointing at the same template."""
	frappe.get_doc(
		{
			"doctype": "Event Bus Message Template",
			"template_name": TEMPLATE,
			"enabled": 1,
			"jinja_template": ('{"name": {{ doc.name | json }}, "event": {{ context.event_type | json }}}'),
		}
	).insert(ignore_permissions=True)

	for event_type in event_types:
		frappe.get_doc(
			{
				"doctype": "Event Bus Rule",
				"rule_name": _rule_name(event_type),
				"enabled": 1,
				"reference_doctype": TEST_DOCTYPE,
				"event_type": event_type,
				"message_template": TEMPLATE,
				"destinations": [
					{
						"enabled": 1,
						"provider": "fake",
						"connection": "conn-1",
						"destination": "dest-1",
						"routing_key": "rk",
					}
				],
			}
		).insert(ignore_permissions=True)


def _enable_bus() -> None:
	settings = frappe.get_single("Event Bus Settings")
	settings.enabled = 1
	settings.save(ignore_permissions=True)


def _events_for(docname: str) -> list[str]:
	"""Event types this test's own rules recorded for a document, in order.

	Scoped to our rules so an unrelated rule on the same doctype — left behind
	by another test or by manual work on the site — cannot change the result.
	"""
	return frappe.get_all(
		"Event Bus Outbox Message",
		filters={
			"reference_doctype": TEST_DOCTYPE,
			"reference_document": docname,
			"event_rule": ["in", [_rule_name(e) for e in EVENT_TYPES]],
		},
		fields=["event_type"],
		order_by="creation asc, name asc",
		pluck="event_type",
	)


class TestLifecycleEvents(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_test_doctype()

	@classmethod
	def tearDownClass(cls):
		_drop_test_doctype()
		super().tearDownClass()

	def setUp(self):
		register_fake_provider()
		_cleanup()
		_setup_rules()
		_enable_bus()

	def tearDown(self):
		_cleanup()

	def _new_doc(self):
		return frappe.get_doc({"doctype": TEST_DOCTYPE}).insert(ignore_permissions=True)

	def test_insert_fires_after_insert(self):
		doc = self._new_doc()
		self.assertIn("after_insert", _events_for(doc.name))

	def test_save_fires_on_update(self):
		doc = self._new_doc()
		before = _events_for(doc.name)
		doc.save(ignore_permissions=True)
		new = _events_for(doc.name)[len(before) :]
		self.assertIn("on_update", new)

	def test_submit_fires_on_submit(self):
		doc = self._new_doc()
		before = _events_for(doc.name)
		doc.submit()
		self.assertIn("on_submit", _events_for(doc.name)[len(before) :])

	def test_cancel_fires_on_cancel(self):
		doc = self._new_doc()
		doc.submit()
		before = _events_for(doc.name)
		doc.cancel()
		self.assertIn("on_cancel", _events_for(doc.name)[len(before) :])

	def test_delete_fires_on_trash(self):
		doc = self._new_doc()
		name = doc.name
		before = _events_for(name)
		doc.delete()
		self.assertIn("on_trash", _events_for(name)[len(before) :])

	def test_every_hooked_event_is_reachable(self):
		"""The whole lifecycle covers all five hooked events."""
		doc = self._new_doc()
		doc.save(ignore_permissions=True)
		doc.submit()
		doc.cancel()
		name = doc.name
		doc.delete()
		self.assertEqual(set(_events_for(name)), set(EVENT_TYPES))

	def test_a_rule_only_fires_for_its_own_event(self):
		"""A rule bound to on_trash must not fire on insert."""
		_cleanup()
		_setup_rules(("on_trash",))
		doc = self._new_doc()
		self.assertEqual(_events_for(doc.name), [])
		name = doc.name
		doc.delete()
		self.assertEqual(_events_for(name), ["on_trash"])

	def test_payload_carries_the_triggering_event(self):
		doc = self._new_doc()
		payload = frappe.get_all(
			"Event Bus Outbox Message",
			filters={
				"reference_document": doc.name,
				"event_rule": _rule_name("after_insert"),
			},
			fields=["payload"],
		)[0].payload
		self.assertEqual(frappe.parse_json(payload)["event"], "after_insert")
