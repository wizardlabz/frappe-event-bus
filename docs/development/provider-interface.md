# Provider Interface

Frappe Event Bus is broker-agnostic. The **core** app (this app) owns rules,
templates, the outbox and the worker. **Provider apps** (e.g. a RabbitMQ or Kafka
app) implement the transport. A provider app contributes itself through the
`event_bus_providers` hook and ships an `EventBusProvider` subclass.

## 1. Registering a provider

In the provider app's `hooks.py`:

```python
event_bus_providers = [
    "my_rabbitmq_app.providers.rabbitmq.get_provider_spec",
]
```

Each entry is a dotted path to a **callable returning a provider spec dict**:

```python
def get_provider_spec() -> dict:
    return {
        "name": "rabbitmq",                                   # unique key, used in rules
        "label": "RabbitMQ",                                  # human label
        "connection_doctype": "Event Bus RabbitMQ Connection",
        "destination_doctype": "Event Bus RabbitMQ Exchange",
        "publisher": "my_rabbitmq_app.providers.rabbitmq.RabbitMQPublisher",
    }
```

The core resolves specs via `frappe_event_bus.providers.registry`:

- `get_providers() -> dict[str, dict]` — `{spec["name"]: spec}` (cached per request).
- `get_provider(name) -> dict` — one spec, or `frappe.throw` if missing.
- `get_publisher(name) -> EventBusProvider` — instantiates `spec["publisher"]`.

## 2. The publisher class

Subclass `frappe_event_bus.providers.interface.EventBusProvider`:

```python
from frappe_event_bus.providers.interface import (
    EventBusProvider, publish_success, publish_failure,
)

class RabbitMQPublisher(EventBusProvider):
    def validate_connection(self, connection_doc) -> None: ...
    def validate_destination(self, destination_doc) -> None: ...

    def publish(self, message: dict) -> dict:
        connection = frappe.get_doc("Event Bus RabbitMQ Connection", message["connection"])
        destination = frappe.get_doc("Event Bus RabbitMQ Exchange", message["destination"])
        try:
            msg_id = _do_publish(connection, destination, message)
            return publish_success(provider_message_id=msg_id)
        except TransientBrokerError as exc:
            return publish_failure(str(exc), retryable=True)
        except PermanentConfigError as exc:
            return publish_failure(str(exc), retryable=False)

    def test_publish(self, connection_doc, destination_doc, payload: dict, headers=None) -> dict:
        ...
```

The provider is responsible for loading its own connection/destination docs from
the docnames carried in the message.

## 3. Normalized result contract

`publish` and `test_publish` MUST return one of these exact shapes (build them
with the helpers so they never drift):

```python
publish_success(provider_message_id=None, response=None)
# -> {"success": True, "provider_message_id": <str|None>, "response": <dict>}

publish_failure(error, retryable=True)
# -> {"success": False, "error": <str>, "retryable": <bool>}
```

The worker uses `retryable` to decide between **Retry Scheduled** (retryable and
attempts remaining), **Failed** (retryable but attempts exhausted) and
**Dead Lettered** (non-retryable).

## 4. The message dict passed to `publish(message)`

The core builds this plain dict from an Outbox Message and passes it verbatim:

```python
{
    "outbox_name": str,            # Outbox Message docname
    "provider": str,               # e.g. "rabbitmq"
    "connection": str,             # connection docname (provider loads it itself)
    "destination": str,            # provider-specific destination docname
    "routing_key": str | None,     # optional override from the rule destination
    "payload": dict,               # parsed rendered payload
    "payload_json": str,           # raw JSON string
    "headers": dict,
    "reference_doctype": str,
    "reference_name": str,
    "event_type": str,             # after_insert|on_update|on_submit|on_cancel|on_trash
    "deduplication_key": str | None,
}
```

These keys are stable; a provider may rely on all of them being present.
