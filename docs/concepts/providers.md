# Providers

The core knows nothing about any broker. Everything broker-specific — connection fields, destination fields, dependencies, publishing code — lives in a separate Frappe app that registers itself with the core.

## Why separate apps

A provider is a full Frappe app rather than a Python module, so it can ship its own DocTypes, fixtures, hooks, permissions, and install lifecycle. That buys three things:

- Provider dependencies (`pika`, `confluent-kafka`, …) stay out of the core.
- Installation is opt-in — you install only the brokers you use.
- A change to one provider cannot break the core or another provider.

The cost is a registry and some versioning discipline, which is the trade this project takes deliberately.

## Registration

A provider app declares a hook in its `hooks.py`:

```python
event_bus_providers = ["frappe_event_bus_rabbitmq.provider.get_provider"]
```

Each entry is a dotted path to a callable returning a spec:

```python
def get_provider():
    return {
        "name": "rabbitmq",
        "label": "RabbitMQ",
        "connection_doctype": "RabbitMQ Event Bus Connection",
        "destination_doctype": "RabbitMQ Event Bus Destination",
        "publisher": "frappe_event_bus_rabbitmq.publisher.RabbitMQPublisher",
    }
```

The core resolves every registered hook, keys the specs by `name`, and caches the result on `frappe.local` for the duration of the request. `name` is what you type into a rule destination's `provider` field.

Publishing a message to an unregistered provider raises a clear error — *"Event Bus provider 'x' is not registered"* — rather than failing obscurely. Since a provider raising is treated as a retryable failure, uninstalling a provider app leaves its messages retrying rather than dead.

## The publish interface

Providers subclass `EventBusProvider`:

```python
class EventBusProvider:
    def validate_connection(self, connection_doc) -> None: ...
    def validate_destination(self, destination_doc) -> None: ...
    def publish(self, message: dict) -> dict: ...
    def test_publish(self, connection_doc, destination_doc, payload, headers=None) -> dict: ...
```

Every method raises `NotImplementedError` in the base class, so a partial implementation fails loudly.

## The result contract

`publish` and `test_publish` must return one of two shapes. Helpers build them:

```python
from frappe_event_bus.providers.interface import publish_success, publish_failure

publish_success("broker-msg-id", {"confirmed": True})
# {"success": True, "provider_message_id": "broker-msg-id", "response": {"confirmed": True}}

publish_failure("Connection refused", retryable=True)
# {"success": False, "error": "Connection refused", "retryable": True}
```

`retryable` is the single most consequential field a provider sets. It decides whether a failure is rescheduled with backoff or dead-lettered immediately. Classify authentication and configuration errors as non-retryable; classify network and timeout errors as retryable.

## Installed providers

| Provider | Status |
|---|---|
| [RabbitMQ](https://github.com/wizardlabz/frappe-event-bus-rabbitmq) | Available |
| Kafka | Planned |
| NATS | Planned |

## Version compatibility

A provider's major version must match the core's:

```
frappe_event_bus_rabbitmq 1.2.0 supports frappe_event_bus >=1.0,<2.0
```

## Not yet available

The plan describes a consume interface with two contracts — per-message acknowledgement for RabbitMQ-style brokers, batch commit for Kafka-style ones — plus a provider diagnostics page listing installed providers and their health. Neither ships today; both are v0.3 work. Only the publish path above exists.

## Related

- [Writing a provider](../development/writing-a-provider.md)
- [Provider interface reference](../development/provider-interface.md)
- [Destinations](destinations.md) — how a rule names a provider
