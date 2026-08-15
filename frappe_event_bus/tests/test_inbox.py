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


from frappe_event_bus.consumer.inbox import persist_message

CONSUMER_DOC = "_Test EB Persist Consumer"


def _consumer_doc():
	frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER_DOC, force=1)
	return frappe.get_doc(
		{
			"doctype": "Event Bus Consumer",
			"consumer_name": CONSUMER_DOC,
			"provider": "fake",
			"connection": "c",
			"source_type": "RabbitMQ Queue",
			"source": "test.queue",
			"deduplication_strategy": "Payload Field",
			"deduplication_key_expression": "order_id",
			"message_type_detection": "Payload Field",
			"message_type_source": "message_type",
		}
	).insert(ignore_permissions=True)


def _incoming(order_id: str = "SO-1"):
	raw = f'{{"order_id": "{order_id}", "message_type": "OrderCreated"}}'
	return {
		"provider_message_id": "amqp-1",
		"payload_raw": raw,
		"payload": frappe.parse_json(raw),
		"headers": {},
		"routing_key": "order.created",
		"source": "test.queue",
		"raw_metadata": {},
	}


class TestPersistMessage(FrappeTestCase):
	def setUp(self):
		# FrappeTestCase only rolls the DB back once per class (see
		# frappe.tests.utils._rollback_db, wired up via addClassCleanup), not
		# after each test method. Two methods here reuse the same default
		# order_id ("SO-1"), so without this cleanup a row left behind by an
		# earlier method collides with the "fresh" insert of a later one.
		frappe.db.delete("Event Bus Inbox Message", {"consumer": CONSUMER_DOC})
		self.consumer = _consumer_doc()

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER_DOC, force=1)

	def test_a_new_message_is_received(self):
		row = persist_message(self.consumer, _incoming())
		self.assertEqual(row.status, "Received")
		self.assertEqual(row.deduplication_key, "SO-1")
		self.assertEqual(row.message_type, "OrderCreated")
		self.assertIsNone(row.duplicate_of)

	def test_a_redelivered_message_is_ignored_and_linked(self):
		"""Redelivery is normal, so it is recorded rather than dropped."""
		original = persist_message(self.consumer, _incoming())
		duplicate = persist_message(self.consumer, _incoming())

		self.assertEqual(duplicate.status, "Ignored")
		self.assertEqual(duplicate.duplicate_of, original.name)
		self.assertEqual(duplicate.duplicate_key, "SO-1")
		self.assertIsNone(duplicate.deduplication_key)
		self.assertEqual(frappe.db.get_value("Event Bus Inbox Message", original.name, "status"), "Received")

	def test_a_non_json_payload_is_stored_intact(self):
		"""A malformed body must not fail the batch."""
		message = _incoming()
		message["payload_raw"] = "not json at all"
		message["payload"] = None
		row = persist_message(self.consumer, message)
		self.assertEqual(row.payload, "not json at all")
		self.assertEqual(row.status, "Received")
