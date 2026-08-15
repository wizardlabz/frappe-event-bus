"""Deduplication key computation. Pure — no database."""

from __future__ import annotations

import hashlib

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.consumer.dedup import compute_dedup_key


def _consumer(strategy: str, expression: str | None = None):
	return frappe._dict(
		name="c1",
		deduplication_strategy=strategy,
		deduplication_key_expression=expression,
	)


def _message(**overrides):
	message = {
		"provider_message_id": "amqp-1",
		"payload_raw": '{"order_id": "SO-1"}',
		"payload": {"order_id": "SO-1"},
		"headers": {"x-id": "H-9"},
		"routing_key": "order.created",
	}
	message.update(overrides)
	return message


class TestDedupKey(FrappeTestCase):
	def test_payload_hash_is_the_sha256_of_the_raw_body(self):
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		self.assertEqual(compute_dedup_key(_consumer("Payload Hash"), _message()), expected)

	def test_external_message_id_uses_the_broker_id(self):
		self.assertEqual(compute_dedup_key(_consumer("External Message ID"), _message()), "amqp-1")

	def test_header_value_reads_the_named_header(self):
		key = compute_dedup_key(_consumer("Header Value", "x-id"), _message())
		self.assertEqual(key, "H-9")

	def test_payload_field_reads_the_named_field(self):
		key = compute_dedup_key(_consumer("Payload Field", "order_id"), _message())
		self.assertEqual(key, "SO-1")

	def test_custom_expression_can_scope_the_key_to_the_consumer(self):
		"""The documented escape hatch from global deduplication scope."""
		consumer = _consumer("Custom Expression", "{{ consumer.name }}-{{ payload.order_id }}")
		self.assertEqual(compute_dedup_key(consumer, _message()), "c1-SO-1")

	def test_an_empty_expression_falls_back_to_the_payload_hash(self):
		"""A misconfigured expression must never disable deduplication."""
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		consumer = _consumer("Custom Expression", "{{ payload.missing }}")
		self.assertEqual(compute_dedup_key(consumer, _message()), expected)

	def test_a_missing_broker_id_falls_back_to_the_payload_hash(self):
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		message = _message(provider_message_id=None)
		self.assertEqual(compute_dedup_key(_consumer("External Message ID"), message), expected)

	def test_a_partially_resolved_expression_falls_back_to_the_payload_hash(self):
		"""A half-rendered key would collide across unrelated messages."""
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		consumer = _consumer("Custom Expression", "{{ consumer.name }}-{{ payload.missing }}")
		self.assertEqual(compute_dedup_key(consumer, _message()), expected)

	def test_a_missing_field_in_a_dict_payload_falls_back_to_the_payload_hash(self):
		"""frappe._dict returns None for a missing key rather than raising."""
		raw = '{"order_id": "SO-1"}'
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(payload=frappe.parse_json(raw), payload_raw=raw)
		consumer = _consumer("Custom Expression", "{{ payload.missing }}")
		self.assertEqual(compute_dedup_key(consumer, message), expected)

	def test_two_messages_missing_the_same_field_do_not_collide(self):
		"""The failure that makes this critical: identical keys discard traffic."""
		consumer = _consumer("Custom Expression", "{{ payload.missing }}")
		first = _message(
			payload=frappe.parse_json('{"order_id": "SO-1"}'), payload_raw='{"order_id": "SO-1"}'
		)
		second = _message(
			payload=frappe.parse_json('{"order_id": "SO-2"}'), payload_raw='{"order_id": "SO-2"}'
		)
		self.assertNotEqual(compute_dedup_key(consumer, first), compute_dedup_key(consumer, second))

	def test_a_json_string_payload_falls_back_to_the_payload_hash(self):
		"""A broker may publish valid JSON that is not an object."""
		raw = '"just a string"'
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(payload=frappe.parse_json(raw), payload_raw=raw)
		consumer = _consumer("Custom Expression", "{{ payload.order_id }}")
		self.assertEqual(compute_dedup_key(consumer, message), expected)

	def test_a_json_array_payload_falls_back_to_the_payload_hash(self):
		raw = "[1, 2, 3]"
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(payload=frappe.parse_json(raw), payload_raw=raw)
		consumer = _consumer("Custom Expression", "{{ payload.order_id }}")
		self.assertEqual(compute_dedup_key(consumer, message), expected)

	def test_payload_field_survives_a_json_array_payload(self):
		"""Payload Field reads a named field, and a list has none.

		This is the default-configuration case: frappe.parse_json returns a
		plain list for '[1, 2, 3]', which has no .get at all.
		"""
		raw = "[1, 2, 3]"
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(payload=frappe.parse_json(raw), payload_raw=raw)
		self.assertEqual(compute_dedup_key(_consumer("Payload Field", "order_id"), message), expected)

	def test_payload_field_survives_a_bare_string_payload(self):
		raw = '"hello"'
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(payload=frappe.parse_json(raw), payload_raw=raw)
		self.assertEqual(compute_dedup_key(_consumer("Payload Field", "order_id"), message), expected)

	def test_header_value_survives_a_non_mapping_header_set(self):
		"""Headers arrive from the provider and are not guaranteed to be a map."""
		raw = '{"order_id": "SO-1"}'
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(headers=frappe.parse_json("[1, 2, 3]"), payload_raw=raw)
		self.assertEqual(compute_dedup_key(_consumer("Header Value", "x-id"), message), expected)

	def test_header_value_survives_a_bare_string_header_set(self):
		raw = '{"order_id": "SO-1"}'
		expected = hashlib.sha256(raw.encode()).hexdigest()
		message = _message(headers=frappe.parse_json('"hello"'), payload_raw=raw)
		self.assertEqual(compute_dedup_key(_consumer("Header Value", "x-id"), message), expected)
