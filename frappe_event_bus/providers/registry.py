"""Provider registry: resolves provider specs declared via the ``event_bus_providers`` hook.

Each hook entry is a dotted path to a callable returning a provider spec dict::

    {
        "name": "rabbitmq",
        "label": "RabbitMQ",
        "connection_doctype": "Event Bus RabbitMQ Connection",
        "destination_doctype": "Event Bus RabbitMQ Destination",
        "publisher": "some_app.providers.rabbitmq.RabbitMQPublisher",
    }
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe_event_bus.providers.interface import EventBusProvider

HOOK_KEY = "event_bus_providers"
_CACHE_KEY = "event_bus_providers_cache"


def clear_cache() -> None:
	"""Drop the per-request provider cache (used by tests)."""
	if hasattr(frappe.local, "_event_bus_provider_cache"):
		del frappe.local._event_bus_provider_cache


def get_providers() -> dict[str, dict[str, Any]]:
	"""Resolve all registered provider specs keyed by ``spec["name"]``.

	Results are cached on ``frappe.local`` for the duration of the request.
	"""
	cached = getattr(frappe.local, "_event_bus_provider_cache", None)
	if cached is not None:
		return cached

	specs: dict[str, dict[str, Any]] = {}
	for dotted_path in frappe.get_hooks(HOOK_KEY) or []:
		spec = frappe.get_attr(dotted_path)()
		specs[spec["name"]] = spec

	frappe.local._event_bus_provider_cache = specs
	return specs


def get_provider(name: str) -> dict[str, Any]:
	"""Return the spec for ``name`` or raise a user-facing error."""
	spec = get_providers().get(name)
	if not spec:
		frappe.throw(frappe._("Event Bus provider '{0}' is not registered.").format(name))
	return spec


def get_publisher(name: str) -> EventBusProvider:
	"""Instantiate and return the publisher class for provider ``name``."""
	spec = get_provider(name)
	publisher_class = frappe.get_attr(spec["publisher"])
	return publisher_class()
