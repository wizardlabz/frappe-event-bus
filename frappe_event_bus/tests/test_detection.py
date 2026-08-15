"""Message-type detection. Pure — no database."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.consumer.detection import detect_message_type


def _consumer(mode: str, source: str | None = None):
	return frappe._dict(message_type_detection=mode, message_type_source=source)


def _message(**overrides):
	message = {
		"payload": {"message_type": "OrderCreated"},
		"headers": {"message_type": "HeaderType"},
		"routing_key": "order.created",
	}
	message.update(overrides)
	return message


class TestMessageTypeDetection(FrappeTestCase):
	def test_payload_field_reads_the_named_field(self):
		self.assertEqual(
			detect_message_type(_consumer("Payload Field", "message_type"), _message()),
			"OrderCreated",
		)

	def test_header_reads_the_named_header(self):
		self.assertEqual(detect_message_type(_consumer("Header", "message_type"), _message()), "HeaderType")

	def test_routing_key_uses_the_routing_key(self):
		self.assertEqual(detect_message_type(_consumer("Routing Key"), _message()), "order.created")

	def test_fixed_uses_the_configured_value(self):
		self.assertEqual(detect_message_type(_consumer("Fixed", "AlwaysThis"), _message()), "AlwaysThis")

	def test_a_missing_field_yields_none_rather_than_raising(self):
		"""An undetectable type is recorded as unknown, not a failed ingest."""
		self.assertIsNone(detect_message_type(_consumer("Payload Field", "absent"), _message()))

	def test_a_non_json_payload_yields_none(self):
		message = _message(payload=None)
		self.assertIsNone(detect_message_type(_consumer("Payload Field", "message_type"), message))
