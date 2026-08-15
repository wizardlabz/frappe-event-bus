"""In-memory consume session used by the consumer tests.

Mirrors ``fake_provider`` on the publishing side: state lives in
``frappe.flags`` so a test can queue messages, then inspect what was
acknowledged or rejected.
"""

from __future__ import annotations

from typing import Any

import frappe


def queue_messages(messages: list[dict[str, Any]]) -> None:
	"""Make ``messages`` available to the next receive call."""
	normalized = []
	for index, message in enumerate(messages):
		normalized.append(
			{
				"provider_message_id": message.get("provider_message_id"),
				"payload_raw": message.get("payload_raw", "{}"),
				"payload": message.get("payload", frappe.parse_json(message.get("payload_raw", "{}"))),
				"headers": message.get("headers", {}),
				"routing_key": message.get("routing_key"),
				"source": message.get("source", "test.queue"),
				"raw_metadata": message.get("raw_metadata", {}),
				"_handle": index,
			}
		)
	frappe.flags.fake_consume_queue = normalized


def take_acked() -> list[dict[str, Any]]:
	"""Return and clear the acknowledged messages."""
	acked = frappe.flags.get("fake_consume_acked") or []
	frappe.flags.fake_consume_acked = []
	return acked


def take_rejected() -> list[dict[str, Any]]:
	"""Return and clear the rejected messages."""
	rejected = frappe.flags.get("fake_consume_rejected") or []
	frappe.flags.fake_consume_rejected = []
	return rejected


class FakeConsumeSession:
	"""Serves queued messages and records acknowledgements."""

	def __init__(self, consumer: Any) -> None:
		self.consumer = consumer

	def receive(self, max_messages: int) -> list[dict[str, Any]]:
		queued = frappe.flags.get("fake_consume_queue") or []
		taken, frappe.flags.fake_consume_queue = queued[:max_messages], queued[max_messages:]
		return taken

	def ack(self, message: dict[str, Any]) -> None:
		frappe.flags.setdefault("fake_consume_order", []).append("ack")
		if frappe.flags.get("fake_consume_ack_raises"):
			raise RuntimeError("simulated crash before ack")
		frappe.flags.setdefault("fake_consume_acked", []).append(message)

	def reject(self, message: dict[str, Any], requeue: bool = False) -> None:
		frappe.flags.setdefault("fake_consume_rejected", []).append(message)

	def __enter__(self) -> FakeConsumeSession:
		return self

	def __exit__(self, *exc_info: Any) -> None:
		return None


def open_fake_session(consumer: Any) -> FakeConsumeSession:
	"""Provider-side factory referenced by the fake provider spec."""
	return FakeConsumeSession(consumer)


def register_fake_consume_provider(contract: str = "per_message") -> None:
	"""Prime the registry cache with a consuming fake provider."""
	frappe.local._event_bus_provider_cache = {
		"fake": {
			"name": "fake",
			"label": "Fake Provider",
			"connection_doctype": "Event Bus Settings",
			"destination_doctype": "Event Bus Settings",
			"publisher": "frappe_event_bus.tests.fake_provider.FakePublisher",
			"consumer": "frappe_event_bus.tests.fake_consume_provider.open_fake_session",
			"consume_contract": contract,
		}
	}
	frappe.flags.fake_consume_queue = []
	frappe.flags.fake_consume_acked = []
	frappe.flags.fake_consume_rejected = []
	frappe.flags.fake_consume_ack_raises = False
	frappe.flags.fake_consume_order = []
