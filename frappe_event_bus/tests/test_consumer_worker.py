"""Consumer configuration and the polling worker."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

CONSUMER = "_Test EB Consumer"


def _make_consumer(**overrides) -> frappe.model.document.Document:
	values = {
		"doctype": "Event Bus Consumer",
		"consumer_name": CONSUMER,
		"provider": "fake",
		"connection": "conn-1",
		"source_type": "RabbitMQ Queue",
		"source": "test.queue",
	}
	values.update(overrides)
	return frappe.get_doc(values).insert(ignore_permissions=True)


class TestConsumerDocType(FrappeTestCase):
	def setUp(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_a_new_consumer_is_disabled(self):
		"""Consuming is sensitive, so it must never switch itself on."""
		consumer = _make_consumer()
		self.assertEqual(consumer.enabled, 0)

	def test_defaults_are_set(self):
		consumer = _make_consumer()
		self.assertEqual(consumer.batch_size, 25)
		self.assertEqual(consumer.poll_interval, 60)
		self.assertEqual(consumer.deduplication_strategy, "Payload Hash")
		self.assertEqual(consumer.max_payload_bytes, 1048576)

	def test_dedicated_worker_mode_is_rejected(self):
		"""The field exists from this phase, but only polling is implemented."""
		with self.assertRaises(frappe.ValidationError):
			_make_consumer(consumption_mode="Dedicated Worker")


from frappe_event_bus.consumer.contract import open_consume_session
from frappe_event_bus.tests.fake_consume_provider import (
	queue_messages,
	register_fake_consume_provider,
	take_acked,
)


class TestConsumeContract(FrappeTestCase):
	def setUp(self):
		register_fake_consume_provider()
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_a_session_receives_and_acknowledges(self):
		consumer = _make_consumer()
		queue_messages([{"payload_raw": '{"a": 1}', "provider_message_id": "m1"}])
		with open_consume_session(consumer) as session:
			messages = session.receive(10)
			self.assertEqual(len(messages), 1)
			session.ack(messages[0])
		self.assertEqual([m["provider_message_id"] for m in take_acked()], ["m1"])

	def test_an_unsupported_contract_is_refused_by_name(self):
		register_fake_consume_provider(contract="batch_commit")
		consumer = _make_consumer()
		with self.assertRaises(NotImplementedError) as ctx:
			open_consume_session(consumer)
		self.assertIn("batch_commit", str(ctx.exception))
