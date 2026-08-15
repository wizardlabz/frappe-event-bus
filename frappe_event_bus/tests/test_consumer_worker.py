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

	def test_a_key_strategy_without_an_expression_is_rejected(self):
		"""Blank, these strategies silently deduplicate on the body instead.

		They would look up the empty string, find nothing, and fall back to the
		payload hash — and under the Inbox's global deduplication scope two
		distinct messages with identical bodies (a repeated heartbeat) then
		collide and the second is discarded.
		"""
		for strategy in ("Header Value", "Payload Field", "Custom Expression"):
			with self.subTest(strategy=strategy):
				frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)
				with self.assertRaises(frappe.ValidationError):
					_make_consumer(deduplication_strategy=strategy)

	def test_a_key_strategy_with_an_expression_is_accepted(self):
		consumer = _make_consumer(
			deduplication_strategy="Payload Field",
			deduplication_key_expression="order_id",
		)
		self.assertEqual(consumer.deduplication_key_expression, "order_id")

	def test_the_keyless_strategies_need_no_expression(self):
		for strategy in ("Payload Hash", "External Message ID"):
			with self.subTest(strategy=strategy):
				frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)
				consumer = _make_consumer(deduplication_strategy=strategy)
				self.assertEqual(consumer.deduplication_strategy, strategy)


from frappe_event_bus.consumer.contract import open_consume_session
from frappe_event_bus.tests.fake_consume_provider import (
	queue_messages,
	register_fake_consume_provider,
	take_acked,
	take_rejected,
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


from frappe.utils import add_to_date, now_datetime

from frappe_event_bus.consumer import worker as cw


class TestDueAndClaim(FrappeTestCase):
	def setUp(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_a_consumer_that_never_polled_is_due(self):
		consumer = _make_consumer()
		self.assertTrue(cw.is_due(consumer))

	def test_a_recently_polled_consumer_is_not_due(self):
		consumer = _make_consumer(poll_interval=300)
		consumer.db_set("last_polled_at", now_datetime())
		consumer.reload()
		self.assertFalse(cw.is_due(consumer))

	def test_a_consumer_past_its_interval_is_due(self):
		consumer = _make_consumer(poll_interval=60)
		consumer.db_set("last_polled_at", add_to_date(now_datetime(), seconds=-120))
		consumer.reload()
		self.assertTrue(cw.is_due(consumer))

	def test_only_the_first_claimer_wins(self):
		consumer = _make_consumer()
		self.assertTrue(cw.claim_consumer(consumer.name))
		self.assertFalse(cw.claim_consumer(consumer.name))

	def test_releasing_allows_a_later_claim(self):
		consumer = _make_consumer()
		cw.claim_consumer(consumer.name)
		cw.release_consumer(consumer.name)
		self.assertTrue(cw.claim_consumer(consumer.name))

	def test_a_stale_claim_can_be_taken_over(self):
		"""A worker killed mid-cycle must not strand its consumer forever."""
		consumer = _make_consumer(poll_interval=60)
		consumer.db_set("claimed_at", add_to_date(now_datetime(), seconds=-3600))
		self.assertTrue(cw.claim_consumer(consumer.name))

	def test_claim_returns_false_when_the_row_is_locked(self):
		"""The claim itself swallows the deadlock rather than propagating it.

		Two workers overlapping on the same consumer is exactly the case
		claiming exists for, so losing that race must not surface as an error.
		"""
		consumer = _make_consumer()

		original_sql = frappe.db.sql

		def deadlocking_sql(query, *args, **kwargs):
			# Matched on the statement shape, not its text: the claim is built
			# by the query builder, which chooses its own quoting and
			# parameterizes values, so neither the spacing nor the literal
			# claimed_at value is ours to predict. Only the claim runs after
			# this patch is installed.
			text = str(query)
			if "UPDATE" in text and "Event Bus Consumer" in text:
				raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")
			return original_sql(query, *args, **kwargs)

		frappe.db.sql = deadlocking_sql
		try:
			self.assertFalse(cw.claim_consumer(consumer.name))
		finally:
			frappe.db.sql = original_sql


class TestPollCycle(FrappeTestCase):
	def setUp(self):
		register_fake_consume_provider()
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)
		# FrappeTestCase only rolls the DB back once per class, not after each
		# test method. Every method here reuses the same consumer name, so
		# without this cleanup a row left behind by an earlier method inflates
		# the count assertions of a later one.
		frappe.db.delete("Event Bus Inbox Message", {"consumer": CONSUMER})

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_received_messages_are_persisted_and_acknowledged(self):
		consumer = _make_consumer(enabled=1)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])

		counts = cw.poll_consumer(consumer.name)

		self.assertEqual(counts["received"], 1)
		self.assertEqual([m["provider_message_id"] for m in take_acked()], ["m1"])
		self.assertEqual(frappe.db.count("Event Bus Inbox Message", {"consumer": consumer.name}), 1)

	def test_an_oversized_message_is_rejected_without_requeue(self):
		"""A poison giant message must not be redelivered forever."""
		consumer = _make_consumer(enabled=1, max_payload_bytes=10)
		queue_messages([{"payload_raw": '{"n": "' + "x" * 500 + '"}', "provider_message_id": "big"}])

		counts = cw.poll_consumer(consumer.name)

		self.assertEqual(counts["rejected"], 1)
		self.assertEqual(counts["received"], 0)
		self.assertEqual([m["provider_message_id"] for m in take_rejected()], ["big"])

	def test_the_commit_precedes_every_acknowledgement(self):
		"""The ordering rule, asserted directly.

		A message acknowledged before its row is committed would be lost
		outright if the process died in between — the broker would consider it
		delivered and never send it again.
		"""
		consumer = _make_consumer(enabled=1)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])

		original_commit = frappe.db.commit

		def recording_commit():
			frappe.flags.setdefault("fake_consume_order", []).append("commit")
			return original_commit()

		frappe.db.commit = recording_commit
		try:
			cw.poll_consumer(consumer.name)
		finally:
			frappe.db.commit = original_commit

		self.assertEqual(frappe.flags.fake_consume_order, ["commit", "ack"])

	def test_a_failed_acknowledgement_leaves_the_message_stored_and_deduped_on_redelivery(self):
		"""A failed ack does not prevent persistence, and redelivery is deduped.

		This does not prove the commit happens before the ack (see
		``test_the_commit_precedes_every_acknowledgement`` for that); it proves
		that persistence survives regardless of what happens to the ack.
		"""
		consumer = _make_consumer(enabled=1)
		body = '{"n": 7}'
		queue_messages([{"payload_raw": body, "provider_message_id": "m1"}])

		# Simulate dying between commit and acknowledgement.
		frappe.flags.fake_consume_ack_raises = True
		try:
			with self.assertRaises(RuntimeError):
				cw.poll_consumer(consumer.name)
		finally:
			frappe.flags.fake_consume_ack_raises = False

		# The row is there despite the ack never landing — that is the proof.
		rows = frappe.get_all(
			"Event Bus Inbox Message",
			filters={"consumer": consumer.name},
			fields=["name", "status"],
		)
		self.assertEqual([r.status for r in rows], ["Received"])

		# The broker, never having been acked, delivers it again.
		queue_messages([{"payload_raw": body, "provider_message_id": "m1"}])
		counts = cw.poll_consumer(consumer.name)

		self.assertEqual(counts["ignored"], 1)
		self.assertEqual(counts["received"], 0)
		after = frappe.get_all(
			"Event Bus Inbox Message",
			filters={"consumer": consumer.name},
			fields=["status", "duplicate_of"],
			order_by="creation asc",
		)
		self.assertEqual([r.status for r in after], ["Received", "Ignored"])
		self.assertEqual(after[1].duplicate_of, rows[0].name)

	def test_the_dispatcher_skips_disabled_consumers(self):
		_make_consumer(enabled=0)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])
		cw.poll_due_consumers()
		self.assertEqual(take_acked(), [])

	def test_the_dispatcher_polls_an_enabled_due_consumer(self):
		consumer = _make_consumer(enabled=1)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])
		counts = cw.poll_due_consumers()
		self.assertEqual(counts["polled"], 1)
		self.assertEqual(frappe.db.count("Event Bus Inbox Message", {"consumer": consumer.name}), 1)
