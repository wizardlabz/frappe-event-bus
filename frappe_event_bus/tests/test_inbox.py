"""Inbox persistence and duplicate handling."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

CONSUMER = "_Test EB Inbox Consumer"


def _ensure_consumer() -> None:
	"""The Inbox's consumer field is a real Link, so the target must exist."""
	if frappe.db.exists("Event Bus Consumer", CONSUMER):
		return
	frappe.get_doc(
		{
			"doctype": "Event Bus Consumer",
			"consumer_name": CONSUMER,
			"provider": "fake",
			"connection": "conn-1",
			"source_type": "RabbitMQ Queue",
			"source": "test.queue",
		}
	).insert(ignore_permissions=True)


def _make_row(dedup_key: str | None, **overrides):
	values = {
		"doctype": "Event Bus Inbox Message",
		"consumer": CONSUMER,
		"provider": "fake",
		"source": "test.queue",
		"payload": '{"a": 1}',
		"status": "Received",
		"deduplication_key": dedup_key,
	}
	values.update(overrides)
	return frappe.get_doc(values).insert(ignore_permissions=True)


class TestInboxUniqueness(FrappeTestCase):
	def setUp(self):
		_ensure_consumer()

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_the_same_key_cannot_be_stored_twice(self):
		"""Deduplication is enforced by the database, not by a lookup."""
		_make_row("key-abc")
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			_make_row("key-abc")

	def test_many_rows_may_have_no_key(self):
		"""Duplicate rows store NULL so they coexist under the unique index."""
		first = _make_row(None, status="Ignored")
		second = _make_row(None, status="Ignored")
		self.assertNotEqual(first.name, second.name)
