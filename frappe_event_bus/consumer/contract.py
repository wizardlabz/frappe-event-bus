"""The consume contract: how the core asks a provider for messages.

Receiving and acknowledging must share one session because broker handles are
connection-scoped — a RabbitMQ delivery tag is only valid on the channel that
delivered it, so acknowledging on a fresh channel is an error. The session is
the unit that owns that lifetime.

Providers declare which contract they implement. Only ``per_message`` exists
today; the dispatch point is here so adding batch-commit later is a branch
rather than a rewrite of the poll loop.
"""

from __future__ import annotations

from typing import Any, Protocol

import frappe

from frappe_event_bus.providers.registry import get_provider

PER_MESSAGE = "per_message"


class ConsumeSession(Protocol):
	"""One connection lifetime. Receive and acknowledge share it."""

	def receive(self, max_messages: int) -> list[dict[str, Any]]: ...

	def ack(self, message: dict[str, Any]) -> None: ...

	def reject(self, message: dict[str, Any], requeue: bool = False) -> None: ...

	def __enter__(self) -> ConsumeSession: ...

	def __exit__(self, *exc_info: Any) -> None: ...


def open_consume_session(consumer: Any) -> ConsumeSession:
	"""Open a consume session for ``consumer``'s provider.

	Raises:
		NotImplementedError: If the provider declares a contract the core does
			not implement yet.
		frappe.ValidationError: If the provider is not registered, or declares
			no consumer factory.
	"""
	spec = get_provider(consumer.provider)
	contract = spec.get("consume_contract", PER_MESSAGE)
	if contract != PER_MESSAGE:
		raise NotImplementedError(
			f"Consume contract {contract!r} is not supported yet. "
			f"Provider {consumer.provider!r} cannot be polled."
		)

	factory_path = spec.get("consumer")
	if not factory_path:
		frappe.throw(frappe._("Provider '{0}' does not support consuming.").format(consumer.provider))
	return frappe.get_attr(factory_path)(consumer)
