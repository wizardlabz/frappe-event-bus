"""In-memory fake provider used by integration tests.

Behaviour is controlled via ``frappe.flags``:

* ``fake_provider_result``: dict returned from ``publish`` (defaults to success).
* ``fake_provider_raise``: if truthy, ``publish`` raises a ``RuntimeError``.
* ``fake_provider_calls``: list that records each published message dict.
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe_event_bus.providers.interface import (
	EventBusProvider,
	publish_success,
)


def fake_provider_spec() -> dict[str, Any]:
	"""Return the provider spec for the fake provider."""
	return {
		"name": "fake",
		"label": "Fake Provider",
		"connection_doctype": "Event Bus Settings",
		"destination_doctype": "Event Bus Settings",
		"publisher": "frappe_event_bus.tests.fake_provider.FakePublisher",
	}


class FakePublisher(EventBusProvider):
	"""Records published messages and returns a controllable result."""

	def publish(self, message: dict[str, Any]) -> dict[str, Any]:
		calls = frappe.flags.setdefault("fake_provider_calls", [])
		calls.append(message)
		if frappe.flags.get("fake_provider_raise"):
			raise RuntimeError("fake provider boom")
		return frappe.flags.get("fake_provider_result") or publish_success("fake-msg-id")

	def test_publish(self, connection_doc, destination_doc, payload, headers=None):
		return publish_success("fake-test-id", {"echo": payload})


def register_fake_provider() -> None:
	"""Prime the registry cache with the fake provider for the current request."""
	frappe.local._event_bus_provider_cache = {"fake": fake_provider_spec()}


def reset_flags() -> None:
	"""Reset test flags between cases."""
	frappe.flags.fake_provider_calls = []
	frappe.flags.fake_provider_result = None
	frappe.flags.fake_provider_raise = False
