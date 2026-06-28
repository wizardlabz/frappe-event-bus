"""Provider interface and the normalized publish result contract.

Provider apps subclass :class:`EventBusProvider` and return the dicts produced
by :func:`publish_success` / :func:`publish_failure` from their ``publish`` and
``test_publish`` implementations. These shapes are the canonical contract the
core relies on.
"""

from __future__ import annotations

from typing import Any


def publish_success(
	provider_message_id: str | None = None,
	response: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Build a normalized success result.

	Args:
		provider_message_id: Broker-assigned message id, if any.
		response: Raw provider response payload.

	Returns:
		Normalized success contract dict.
	"""
	return {
		"success": True,
		"provider_message_id": provider_message_id,
		"response": response or {},
	}


def publish_failure(error: str, retryable: bool = True) -> dict[str, Any]:
	"""Build a normalized failure result.

	Args:
		error: Human-readable error message.
		retryable: Whether the worker should schedule a retry.

	Returns:
		Normalized failure contract dict.
	"""
	return {"success": False, "error": error, "retryable": retryable}


class EventBusProvider:
	"""Base class implemented by provider apps (e.g. RabbitMQ, Kafka).

	All methods raise :class:`NotImplementedError` so that a concrete provider
	must override them.
	"""

	def validate_connection(self, connection_doc: Any) -> None:
		"""Validate a connection document; raise on invalid configuration."""
		raise NotImplementedError

	def validate_destination(self, destination_doc: Any) -> None:
		"""Validate a destination document; raise on invalid configuration."""
		raise NotImplementedError

	def publish(self, message: dict[str, Any]) -> dict[str, Any]:
		"""Publish a normalized message dict and return a normalized result."""
		raise NotImplementedError

	def test_publish(
		self,
		connection_doc: Any,
		destination_doc: Any,
		payload: dict[str, Any],
		headers: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""Publish a one-off test payload and return a normalized result."""
		raise NotImplementedError
