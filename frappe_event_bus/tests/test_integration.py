"""Integration tests for the rule engine, outbox worker and replay."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.providers.interface import publish_failure, publish_success
from frappe_event_bus.publisher import outbox_worker as ow
from frappe_event_bus.publisher.outbox_worker import process_message, process_pending
from frappe_event_bus.publisher.replay import replay_outbox_message
from frappe_event_bus.tests.fake_provider import register_fake_provider, reset_flags

TEMPLATE_NAME = "_Test EB Template"
RULE_NAME = "_Test EB Rule"


def _ensure_template() -> str:
	if not frappe.db.exists("Event Bus Message Template", TEMPLATE_NAME):
		frappe.get_doc(
			{
				"doctype": "Event Bus Message Template",
				"template_name": TEMPLATE_NAME,
				"message_type": "todo.event",
				"enabled": 1,
				"jinja_template": '{"todo": "{{ doc.name }}", "priority": "{{ doc.priority }}"}',
			}
		).insert(ignore_permissions=True)
	return TEMPLATE_NAME


def _make_rule(condition: str | None = None, destinations: int = 1) -> str:
	frappe.db.delete("Event Bus Outbox Message", {"event_rule": RULE_NAME})
	frappe.delete_doc_if_exists("Event Bus Rule", RULE_NAME, force=1)
	dest_rows = [
		{
			"enabled": 1,
			"provider": "fake",
			"connection": "conn-1",
			"destination": f"dest-{i}",
			"routing_key": f"rk-{i}",
		}
		for i in range(destinations)
	]
	frappe.get_doc(
		{
			"doctype": "Event Bus Rule",
			"rule_name": RULE_NAME,
			"enabled": 1,
			"reference_doctype": "ToDo",
			"event_type": "after_insert",
			"condition": condition,
			"message_template": _ensure_template(),
			"destinations": dest_rows,
		}
	).insert(ignore_permissions=True)
	return RULE_NAME


def _enable_bus() -> None:
	settings = frappe.get_doc("Event Bus Settings")
	settings.enabled = 1
	settings.max_publish_attempts = 3
	settings.retry_backoff_seconds = 60
	settings.enable_delivery_logging = 1
	settings.save(ignore_permissions=True)
	frappe.clear_document_cache("Event Bus Settings", "Event Bus Settings")


def _make_todo(priority: str = "Medium") -> frappe.Document:
	return frappe.get_doc({"doctype": "ToDo", "description": "eb test", "priority": priority}).insert(
		ignore_permissions=True
	)


def _outbox_for(todo_name: str) -> list[dict]:
	return frappe.get_all(
		"Event Bus Outbox Message",
		filters={"reference_doctype": "ToDo", "reference_document": todo_name},
		fields=["name", "status", "provider", "destination", "routing_key"],
	)


class TestRuleEngine(FrappeTestCase):
	def setUp(self) -> None:
		reset_flags()
		register_fake_provider()
		_enable_bus()

	def test_matching_rule_creates_one_outbox_per_destination(self) -> None:
		_make_rule(destinations=2)
		todo = _make_todo()
		rows = _outbox_for(todo.name)
		self.assertEqual(len(rows), 2)
		self.assertTrue(all(r["status"] == "Pending" for r in rows))
		self.assertEqual({r["destination"] for r in rows}, {"dest-0", "dest-1"})

	def test_condition_true_creates_outbox(self) -> None:
		_make_rule(condition="doc.priority == 'High'")
		todo = _make_todo(priority="High")
		self.assertEqual(len(_outbox_for(todo.name)), 1)

	def test_condition_false_skips(self) -> None:
		_make_rule(condition="doc.priority == 'High'")
		todo = _make_todo(priority="Low")
		self.assertEqual(len(_outbox_for(todo.name)), 0)

	def test_disabled_bus_creates_nothing(self) -> None:
		settings = frappe.get_doc("Event Bus Settings")
		settings.enabled = 0
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache("Event Bus Settings", "Event Bus Settings")
		_make_rule()
		todo = _make_todo()
		self.assertEqual(len(_outbox_for(todo.name)), 0)


class TestOutboxWorker(FrappeTestCase):
	def setUp(self) -> None:
		reset_flags()
		register_fake_provider()
		_enable_bus()

	def _new_outbox(self, attempt_count: int = 0, status: str = "Pending") -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Event Bus Outbox Message",
				"provider": "fake",
				"connection": "conn-1",
				"destination": "dest-1",
				"routing_key": "rk-1",
				"reference_doctype": "ToDo",
				"reference_document": "TODO-XYZ",
				"event_type": "after_insert",
				"payload": '{"hello": "world"}',
				"headers": "{}",
				"status": status,
				"attempt_count": attempt_count,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_success_path(self) -> None:
		name = self._new_outbox()
		outcome = process_message(name)
		self.assertEqual(outcome, "published")
		doc = frappe.get_doc("Event Bus Outbox Message", name)
		self.assertEqual(doc.status, "Published")
		self.assertIsNotNone(doc.published_at)
		self.assertEqual(doc.attempt_count, 1)
		# fake recorded the message with the contract fields
		calls = frappe.flags.fake_provider_calls
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0]["routing_key"], "rk-1")
		self.assertEqual(calls[0]["payload"], {"hello": "world"})
		# delivery attempt logged
		attempts = frappe.get_all(
			"Event Bus Delivery Attempt", filters={"outbox_message": name}, fields=["success"]
		)
		self.assertEqual(len(attempts), 1)
		self.assertTrue(attempts[0]["success"])

	def test_retryable_failure_schedules_retry(self) -> None:
		frappe.flags.fake_provider_result = publish_failure("temporary", retryable=True)
		name = self._new_outbox()
		outcome = process_message(name)
		self.assertEqual(outcome, "retried")
		doc = frappe.get_doc("Event Bus Outbox Message", name)
		self.assertEqual(doc.status, "Retry Scheduled")
		self.assertEqual(doc.attempt_count, 1)
		self.assertIsNotNone(doc.next_retry_at)
		self.assertEqual(doc.last_error, "temporary")

	def test_non_retryable_dead_letters(self) -> None:
		frappe.flags.fake_provider_result = publish_failure("permanent", retryable=False)
		name = self._new_outbox()
		outcome = process_message(name)
		self.assertEqual(outcome, "failed")
		doc = frappe.get_doc("Event Bus Outbox Message", name)
		self.assertEqual(doc.status, "Dead Lettered")

	def test_exhausted_retries_fails(self) -> None:
		frappe.flags.fake_provider_result = publish_failure("temporary", retryable=True)
		# max_publish_attempts = 3; start at attempt_count 2 -> this is attempt 3 -> exhausted
		name = self._new_outbox(attempt_count=2)
		outcome = process_message(name)
		self.assertEqual(outcome, "failed")
		doc = frappe.get_doc("Event Bus Outbox Message", name)
		self.assertEqual(doc.status, "Failed")
		self.assertEqual(doc.attempt_count, 3)

	def test_provider_exception_is_retryable_failure(self) -> None:
		frappe.flags.fake_provider_raise = True
		name = self._new_outbox()
		outcome = process_message(name)
		self.assertEqual(outcome, "retried")
		doc = frappe.get_doc("Event Bus Outbox Message", name)
		self.assertEqual(doc.status, "Retry Scheduled")

	def test_process_pending_batch(self) -> None:
		names = [self._new_outbox() for _ in range(3)]
		counts = process_pending(batch_size=10)
		self.assertGreaterEqual(counts["published"], 3)
		for name in names:
			self.assertEqual(frappe.db.get_value("Event Bus Outbox Message", name, "status"), "Published")

	def test_process_message_skips_already_claimed(self) -> None:
		# A row already Published (claimed + published by another worker) must not
		# be re-published if a stale reference reaches process_message.
		name = self._new_outbox(status="Published")
		outcome = process_message(name)
		self.assertEqual(outcome, "skipped")
		self.assertEqual(len(frappe.flags.fake_provider_calls), 0)

	def test_claim_message_is_atomic(self) -> None:
		# Claiming flips Pending -> Publishing and only the first caller wins.
		name = self._new_outbox()
		self.assertTrue(ow._claim_message(name))
		self.assertEqual(frappe.db.get_value("Event Bus Outbox Message", name, "status"), "Publishing")
		self.assertFalse(ow._claim_message(name))

	def test_batch_isolates_failures(self) -> None:
		# One message raising mid-process must not abort the whole batch.
		names = [self._new_outbox() for _ in range(3)]
		original = ow.process_message

		def flaky(name: str) -> str:
			if name == names[1]:
				raise RuntimeError("simulated db error")
			return original(name)

		ow.process_message = flaky
		try:
			process_pending(batch_size=10)
		finally:
			ow.process_message = original

		self.assertEqual(frappe.db.get_value("Event Bus Outbox Message", names[0], "status"), "Published")
		self.assertEqual(frappe.db.get_value("Event Bus Outbox Message", names[2], "status"), "Published")


class TestReplay(FrappeTestCase):
	def setUp(self) -> None:
		reset_flags()
		register_fake_provider()
		_enable_bus()

	def test_replay_resets_failed_to_pending(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Event Bus Outbox Message",
				"provider": "fake",
				"connection": "conn-1",
				"destination": "dest-1",
				"reference_doctype": "ToDo",
				"reference_document": "TODO-Z",
				"event_type": "after_insert",
				"payload": "{}",
				"headers": "{}",
				"status": "Failed",
				"attempt_count": 3,
				"last_error": "boom",
			}
		).insert(ignore_permissions=True)
		result = replay_outbox_message(doc.name)
		self.assertEqual(result["status"], "Pending")
		refetched = frappe.get_doc("Event Bus Outbox Message", doc.name)
		self.assertEqual(refetched.status, "Pending")
		self.assertIsNone(refetched.last_error)

	def test_replay_resets_attempt_count(self) -> None:
		# A replayed message must get a fresh retry budget, not inherit the old count.
		doc = frappe.get_doc(
			{
				"doctype": "Event Bus Outbox Message",
				"provider": "fake",
				"connection": "conn-1",
				"destination": "dest-1",
				"reference_doctype": "ToDo",
				"reference_document": "TODO-R",
				"event_type": "after_insert",
				"payload": "{}",
				"headers": "{}",
				"status": "Failed",
				"attempt_count": 5,
				"last_error": "boom",
			}
		).insert(ignore_permissions=True)
		replay_outbox_message(doc.name)
		refetched = frappe.get_doc("Event Bus Outbox Message", doc.name)
		self.assertEqual(refetched.attempt_count, 0)

	def test_replay_rejects_pending(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Event Bus Outbox Message",
				"provider": "fake",
				"connection": "conn-1",
				"destination": "dest-1",
				"reference_doctype": "ToDo",
				"reference_document": "TODO-Z",
				"event_type": "after_insert",
				"payload": "{}",
				"headers": "{}",
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			replay_outbox_message(doc.name)
