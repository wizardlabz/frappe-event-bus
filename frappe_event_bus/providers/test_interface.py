"""Unit tests for the provider interface and normalized result helpers."""

import unittest

from frappe_event_bus.providers.interface import (
	EventBusProvider,
	publish_failure,
	publish_success,
)


class TestResultHelpers(unittest.TestCase):
	"""Tests for the normalized publish result contract."""

	def test_publish_success_defaults(self) -> None:
		result = publish_success()
		self.assertEqual(
			result,
			{"success": True, "provider_message_id": None, "response": {}},
		)

	def test_publish_success_with_values(self) -> None:
		result = publish_success("msg-123", {"queued": True})
		self.assertEqual(
			result,
			{"success": True, "provider_message_id": "msg-123", "response": {"queued": True}},
		)

	def test_publish_failure_defaults_retryable(self) -> None:
		result = publish_failure("boom")
		self.assertEqual(result, {"success": False, "error": "boom", "retryable": True})

	def test_publish_failure_non_retryable(self) -> None:
		result = publish_failure("bad config", retryable=False)
		self.assertEqual(result, {"success": False, "error": "bad config", "retryable": False})


class TestEventBusProviderBase(unittest.TestCase):
	"""The base provider must force subclasses to implement behaviour."""

	def setUp(self) -> None:
		self.provider = EventBusProvider()

	def test_validate_connection_not_implemented(self) -> None:
		with self.assertRaises(NotImplementedError):
			self.provider.validate_connection(object())

	def test_validate_destination_not_implemented(self) -> None:
		with self.assertRaises(NotImplementedError):
			self.provider.validate_destination(object())

	def test_publish_not_implemented(self) -> None:
		with self.assertRaises(NotImplementedError):
			self.provider.publish({})

	def test_test_publish_not_implemented(self) -> None:
		with self.assertRaises(NotImplementedError):
			self.provider.test_publish(object(), object(), {})


if __name__ == "__main__":
	unittest.main()
