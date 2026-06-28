"""Unit tests for the provider registry resolution."""

import unittest
from unittest.mock import patch

import frappe

from frappe_event_bus.providers import registry
from frappe_event_bus.providers.interface import EventBusProvider, publish_success


class _FakePublisher(EventBusProvider):
	def publish(self, message: dict) -> dict:
		return publish_success("fake")


def _fake_spec() -> dict:
	return {
		"name": "fake",
		"label": "Fake Provider",
		"connection_doctype": "Fake Connection",
		"destination_doctype": "Fake Destination",
		"publisher": "frappe_event_bus.providers.test_registry._FakePublisher",
	}


class TestRegistry(unittest.TestCase):
	def setUp(self) -> None:
		registry.clear_cache()

	def tearDown(self) -> None:
		registry.clear_cache()

	def test_get_providers_resolves_specs(self) -> None:
		with patch.object(
			frappe, "get_hooks", return_value=["frappe_event_bus.providers.test_registry._fake_spec"]
		):
			providers = registry.get_providers()
		self.assertIn("fake", providers)
		self.assertEqual(providers["fake"]["label"], "Fake Provider")

	def test_get_provider_returns_spec(self) -> None:
		with patch.object(
			frappe, "get_hooks", return_value=["frappe_event_bus.providers.test_registry._fake_spec"]
		):
			spec = registry.get_provider("fake")
		self.assertEqual(spec["publisher"], "frappe_event_bus.providers.test_registry._FakePublisher")

	def test_get_provider_missing_throws(self) -> None:
		with patch.object(frappe, "get_hooks", return_value=[]):
			with self.assertRaises(frappe.ValidationError):
				registry.get_provider("nope")

	def test_get_publisher_instantiates_class(self) -> None:
		with patch.object(
			frappe, "get_hooks", return_value=["frappe_event_bus.providers.test_registry._fake_spec"]
		):
			publisher = registry.get_publisher("fake")
		self.assertIsInstance(publisher, _FakePublisher)
		self.assertEqual(publisher.publish({})["provider_message_id"], "fake")


if __name__ == "__main__":
	unittest.main()
