# Frappe Event Bus

> Bring event-driven architecture to ERPNext and Frappe.

[![CI](https://github.com/wizardlabz/frappe-event-bus/actions/workflows/ci.yml/badge.svg)](https://github.com/wizardlabz/frappe-event-bus/actions/workflows/ci.yml)
[![Linter](https://github.com/wizardlabz/frappe-event-bus/actions/workflows/linter.yml/badge.svg)](https://github.com/wizardlabz/frappe-event-bus/actions/workflows/linter.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Frappe Event Bus is a native Frappe/ERPNext app for publishing **durable, observable, replayable** business events to message brokers — RabbitMQ, Kafka, NATS, and more — without writing custom code.

If you have used **ERPNext Webhooks**, this should feel familiar: you configure *when* an event fires, *what* payload it carries, and *where* it goes. The difference is durability (an outbox), multiple destinations per event, retry/replay, and a pluggable provider model for real message brokers.

> **Positioning:** Frappe Event Bus is not "RabbitMQ for ERPNext." It is a native integration framework for publishing business events. RabbitMQ is simply the first provider.

## Status

**v0.1 — MVP implemented and tested.** The rule engine, message templates, per-destination outbox, background publisher, retry/replay, test-publish, and the provider registry are built and covered by an automated suite (33 passing tests). The [RabbitMQ provider](https://github.com/wizardlabz/frappe-event-bus-rabbitmq) is available separately. APIs may still change before 1.0.

### What's implemented

- **Event Bus Rule** — match a DocType + event (`after_insert`/`on_update`/`on_submit`/`on_cancel`/`on_trash`) with an optional safe condition, fanning out to one or more destinations.
- **Event Bus Message Template** — reusable Jinja→JSON payloads with JSON validation and a Vue-based **payload preview**.
- **Outbox** — one durable row per destination; publishing happens in a background job after the document transaction commits (never blocks the user's save).
- **Worker, retry & replay** — exponential backoff, atomic row-claiming to prevent double-delivery, per-message failure isolation, and one-click replay of failed messages.
- **Provider registry** — brokers register via the `event_bus_providers` hook; the core never imports a broker library.
- **Test publish & diagnostics** — whitelisted endpoints to validate a destination before going live.

## How it works

```
ERPNext / Frappe document event
        ↓
   Rule matcher  →  condition check  →  payload rendered (Jinja → JSON)
        ↓
   One Outbox Message per destination   (durability + isolation)
        ↓
   Background publisher  →  provider.publish()  →  broker
        ↓
   Delivery Attempt log  ·  retry  ·  replay
```

The **core** app owns rules, message templates, the outbox, delivery logging, retry/replay, the permission model, and the provider registry. Each **provider** is a separate Frappe app that implements broker-specific connection, validation, and publishing.

## Architecture: core + provider plugins

| Repo | Purpose |
|------|---------|
| [`frappe-event-bus`](https://github.com/wizardlabz/frappe-event-bus) | Core framework (this repo) |
| [`frappe-event-bus-rabbitmq`](https://github.com/wizardlabz/frappe-event-bus-rabbitmq) | RabbitMQ provider |
| [`frappe-event-bus-kafka`](https://github.com/wizardlabz/frappe-event-bus-kafka) | Kafka provider *(planned)* |
| [`frappe-event-bus-nats`](https://github.com/wizardlabz/frappe-event-bus-nats) | NATS provider *(planned)* |
| [`frappe-event-bus-examples`](https://github.com/wizardlabz/frappe-event-bus-examples) | Example rules & message templates |

Providers register themselves with the core via the `event_bus_providers` hook, so the core never depends on any broker library.

## Installation

Requires a Frappe/ERPNext **v15** bench.

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/wizardlabz/frappe-event-bus --branch main
bench --site <your-site> install-app frappe_event_bus
bench --site <your-site> migrate
```

Then install one or more providers, e.g. RabbitMQ:

```bash
bench get-app https://github.com/wizardlabz/frappe-event-bus-rabbitmq --branch main
bench --site <your-site> install-app frappe_event_bus_rabbitmq
```

## Configure your first integration

1. **Enable the bus** — open *Event Bus Settings* and check **Enabled**.
2. **Create a destination** in your provider app (e.g. a *RabbitMQ Event Bus Connection* + *Destination*), and use its **Test Connection** / **Test Publish** buttons.
3. **Create a Message Template** — write a Jinja→JSON body (e.g. `{"id": "{{ doc.name }}"}`) and click **Preview Payload** to validate it.
4. **Create an Event Bus Rule** — pick the Reference DocType + Event Type, an optional condition (e.g. `doc.disabled == 0`), the template, and add one or more destinations.
5. **Trigger it** — saving a matching document writes an Outbox Message per destination; the background worker publishes them. Watch *Event Bus Outbox Message* and *Event Bus Delivery Attempt* for status, errors, and replay.

A failed message can be re-sent from the Outbox Message with a single **Replay** action.

## Contributing

This app uses `pre-commit` (ruff, eslint, prettier, pyupgrade). After cloning:

```bash
cd apps/frappe_event_bus
pre-commit install
```

## License

[GPL-3.0](license.txt) © WizardLabz
