# Writing a Provider

A provider is a standalone Frappe app that teaches the core how to talk to one broker. This walks through building one. The [RabbitMQ provider](https://github.com/wizardlabz/frappe-event-bus-rabbitmq) is the reference implementation.

For the precise contract, see [provider interface](provider-interface.md).

## 1. Scaffold the app

```bash
bench new-app frappe_event_bus_myqueue
bench --site <your-site> install-app frappe_event_bus_myqueue
```

Depend on the core and fail install clearly when it is missing:

```python
# frappe_event_bus_myqueue/install.py
import frappe

def before_install():
    if "frappe_event_bus" not in frappe.get_installed_apps():
        frappe.throw("Please install Frappe Event Bus before installing this provider.")
```

```python
# hooks.py
before_install = "frappe_event_bus_myqueue.install.before_install"
```

Put the broker library in your app's `pyproject.toml`, never the core's.

## 2. Add connection and destination doctypes

Two doctypes, named for your broker's own vocabulary rather than another broker's:

- **MyQueue Event Bus Connection** — how to reach the broker: host, port, credentials, TLS, timeouts. Store secrets in a `Password` field so Frappe encrypts them.
- **MyQueue Event Bus Destination** — what to publish to: topic, queue, stream, routing key, delivery options.

Resist a single generic destination doctype shared across brokers. Kafka's bootstrap servers, SASL mechanism, and acks have nothing to do with RabbitMQ's exchange type and publisher confirms, and forcing them into shared fields makes both confusing. Distinct doctypes per provider is the point of this design.

## 3. Register with the core

```python
# frappe_event_bus_myqueue/provider.py
def get_provider():
    return {
        "name": "myqueue",
        "label": "MyQueue",
        "connection_doctype": "MyQueue Event Bus Connection",
        "destination_doctype": "MyQueue Event Bus Destination",
        "publisher": "frappe_event_bus_myqueue.publisher.MyQueuePublisher",
    }
```

```python
# hooks.py
event_bus_providers = ["frappe_event_bus_myqueue.provider.get_provider"]
```

`name` is what users type into a rule destination's `provider` field. Keep it short and lowercase.

## 4. Implement the publisher

```python
from frappe_event_bus.providers.interface import (
    EventBusProvider,
    publish_success,
    publish_failure,
)

class MyQueuePublisher(EventBusProvider):
    provider_name = "myqueue"

    def publish(self, message: dict) -> dict:
        connection_doc = frappe.get_doc("MyQueue Event Bus Connection", message["connection"])
        destination_doc = frappe.get_doc("MyQueue Event Bus Destination", message["destination"])
        routing_key = message.get("routing_key") or destination_doc.routing_key

        try:
            msg_id = self._send(
                connection_doc,
                destination_doc,
                message["payload_json"],
                message["headers"],
                routing_key,
            )
        except AuthError as exc:
            return publish_failure(str(exc), retryable=False)
        except (ConnectionError, TimeoutError) as exc:
            return publish_failure(str(exc), retryable=True)

        return publish_success(msg_id)
```

The message dict the core hands you is documented in [The Outbox](../concepts/outbox.md#what-the-provider-receives). Note it carries both `payload` (parsed) and `payload_json` (the exact rendered string) — publish the string if byte fidelity matters.

Also implement `validate_connection`, `validate_destination`, and `test_publish`. The base class raises `NotImplementedError` for each, so anything you skip fails loudly rather than silently.

## 5. Classify errors correctly

This is the decision that matters most, because it determines whether a failure is retried or dead-lettered on the spot.

| Retryable | Not retryable |
|---|---|
| Connection refused, DNS failure | Bad username or password |
| Timeout, broker restarting | Missing permission on a vhost/topic |
| Temporary resource exhaustion | Unroutable message |
| | Precondition failure on an existing topic/queue |

The question to ask is: *would the identical call succeed later without anyone changing configuration?* If no, mark it non-retryable — retrying wastes the attempt budget and delays the dead-letter that tells an operator something is actually wrong.

Do not raise from `publish` for expected broker errors. An uncaught exception is caught by the worker, logged, and treated as **retryable**, so a permanent failure would retry to exhaustion.

## 6. Test it

Mirror the RabbitMQ provider's split:

- **Unit tests** — error classification, validation, destination resolution. No broker needed.
- **Integration tests** — against a real broker as a CI service container. Do not skip when the broker is missing; let it fail loudly, otherwise a broken CI broker silently reports green.

```yaml
services:
  myqueue:
    image: myqueue:latest
    ports: ['5672:5672']
    options: --health-cmd="myqueue-diagnostics ping" --health-interval=10s
```

Cover: successful publish, broker unreachable, invalid credentials, invalid destination, retryable vs non-retryable classification, test publish, and headers.

## 7. Version it

Match the core's major version:

```
frappe_event_bus_myqueue 1.2.0 supports frappe_event_bus >=1.0,<2.0
```

## What the core does not need from you

Rules, templates, the outbox, retry scheduling, replay, delivery logging, retention, and the permission model are all core responsibilities. A provider only handles broker-specific configuration, validation, and the publish call itself.

## Consumers

The plan defines two consume contracts — per-message acknowledgement and batch commit — so providers can match their broker's semantics. Neither exists in the core yet; they arrive in v0.3. Build the publish path today.
