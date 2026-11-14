# Frappe Event Bus — Documentation

Publish durable, observable, replayable business events from Frappe and ERPNext to message brokers, without writing custom code.

For a project overview see the [README](../README.md).

## Start here

| | |
|---|---|
| [Installation](installation.md) | Install the core and a provider, enable the bus. |
| [Getting started](getting-started.md) | Publish your first message end to end. |

## Concepts

| | |
|---|---|
| [Event Rules](concepts/event-rules.md) | Bind a doctype event to a payload and destinations. |
| [Message Templates](concepts/message-templates.md) | Jinja → JSON payloads, schema validation, preview. |
| [Destinations](concepts/destinations.md) | Where messages go; priority, headers, routing keys. |
| [The Outbox](concepts/outbox.md) | Durability, statuses, the worker, double-delivery safety. |
| [Retry and Replay](concepts/retry-and-replay.md) | Backoff, dead-lettering, replay, retention. |
| [Providers](concepts/providers.md) | The registry and the publish interface. |
| [Consumers](concepts/consumers.md) | Receiving messages from a broker into the Inbox. |

## Reference

| | |
|---|---|
| [Settings](reference/settings.md) | Every Event Bus Settings field and scheduled job. |
| [API](reference/api.md) | The six whitelisted methods. |

## Examples

[Example integrations](examples.md) — complete, ready-to-import rules and templates.

## Development

| | |
|---|---|
| [Provider interface](development/provider-interface.md) | The contract every provider implements. |
| [Writing a provider](development/writing-a-provider.md) | Build a provider app from scratch. |
| [Template authoring design](development/template-authoring-design.md) | Why the field picker and preview work the way they do. |
| [Contributing](development/contributing.md) | Tests, linting, commit conventions. |

## How it fits together

```
Frappe / ERPNext document event
        ↓
   Event Bus Rule   →  condition  →  Message Template rendered once
        ↓
   One Outbox Message per destination        (durable, isolated)
        ↓
   Background worker  →  provider.publish()  →  broker
        ↓
   Delivery Attempt  ·  retry with backoff  ·  replay
```

The core owns rules, templates, the outbox, delivery logging, retry, replay, and the provider registry. It never imports a broker library. Each provider is a separate Frappe app contributing its own connection and destination doctypes.

## Scope today

This is the **publisher**: Frappe → broker. Version 0.1 covers rules, templates, the outbox, retry, replay, retention, and the RabbitMQ provider.

The other direction, broker → Frappe, has an ingestion phase: an Event Bus Consumer polls a broker source and writes accepted messages into an Inbox, deduplicated. See [Consumers](concepts/consumers.md). Consumers ship disabled, and nothing yet acts on a message once it is in the Inbox — there is no handler, and no ERPNext document is created or modified by this feature. That processing phase is not built.

---

*This folder (`docs/`) is for documentation intended for end users. Internal notes and drafts live in `_local/`, which is gitignored and never published.*
