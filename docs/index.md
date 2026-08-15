# Frappe Event Bus — Documentation

End-user documentation for Frappe Event Bus. For a project overview and installation, see the [README](../README.md).

## Concepts

- **Event Bus Rule** — binds a Reference DocType + Event Type (`after_insert`, `on_update`, `on_submit`, `on_cancel`, `on_trash`) to a Message Template and a set of destinations. An optional **condition** (a safe Python expression over `doc`) filters which documents fire.
- **Event Bus Message Template** — a reusable Jinja template rendered to a JSON payload. Output is validated as JSON (and against an optional JSON-schema subset). Use **Preview Payload** on the form to check rendering before going live.
- **Destination** — a child row on a Rule: which provider, connection, and provider-specific destination to publish to, plus an optional routing key/headers.
- **Outbox** — when a rule matches, the core renders the payload once and writes **one Outbox Message per destination**, so failures are isolated. Publishing runs in a background job *after* the document transaction commits — it never blocks or rolls back the user's save.
- **Delivery & retry** — the worker claims due messages atomically (no double-delivery), records an **Event Bus Delivery Attempt** per try, and reschedules retryable failures with exponential backoff up to a configurable max. Non-retryable failures are dead-lettered.
- **Replay** — any failed/dead-lettered message can be reset and re-published with a fresh retry budget.

## Settings

*Event Bus Settings* (single doctype): enable/disable the bus, max publish attempts, retry backoff seconds, worker batch size, delivery-logging toggle, retention days.

**Retention** — a daily scheduled job deletes outbox messages (and their delivery attempts) older than *retention days*, but only in the succeeded states `Published` and `Cancelled`. Failed, Dead Lettered and Retry Scheduled messages are kept regardless of age, so retention never destroys the evidence you need to debug a delivery problem. Set it to `0` to disable purging entirely.

**Priority** — each destination row on a rule carries a *priority*. It is copied onto the outbox message, and the worker publishes in ascending order (lower number first), falling back to creation order for ties.

## Providers

The core is broker-agnostic. Install a provider app and it registers itself via the `event_bus_providers` hook:

- [RabbitMQ](https://github.com/wizardlabz/frappe-event-bus-rabbitmq)
- Kafka, NATS — planned.

## Development

- [Provider interface](development/provider-interface.md) — the contract every provider implements (`publish`, `test_publish`, `validate_connection`, `validate_destination`) and the normalized message/result shapes.
- [Template authoring & form layout](development/template-authoring-design.md) — design for the doctype-aware template field picker (`Insert from DocType`), optional `applies_to_doctype` binding, and tabbed form layouts.

---

*This folder (`docs/`) is for documentation intended for end users. Internal notes and drafts live in `_local/`, which is gitignored and never published.*
