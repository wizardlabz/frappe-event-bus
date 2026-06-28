# Frappe Event Bus

> Bring event-driven architecture to ERPNext and Frappe.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Status: early development](https://img.shields.io/badge/status-early%20development-orange.svg)](#status)

Frappe Event Bus is a native Frappe/ERPNext app for publishing **durable, observable, replayable** business events to message brokers — RabbitMQ, Kafka, NATS, and more — without writing custom code.

If you have used **ERPNext Webhooks**, this should feel familiar: you configure *when* an event fires, *what* payload it carries, and *where* it goes. The difference is durability (an outbox), multiple destinations per event, retry/replay, and a pluggable provider model for real message brokers.

> **Positioning:** Frappe Event Bus is not "RabbitMQ for ERPNext." It is a native integration framework for publishing business events. RabbitMQ is simply the first provider.

## Status

🚧 **Early development.** The app scaffolding and dev environment are in place; the rule engine, outbox, and provider interface are being built. Not yet ready for production. Star/watch to follow progress.

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

## Contributing

This app uses `pre-commit` (ruff, eslint, prettier, pyupgrade). After cloning:

```bash
cd apps/frappe_event_bus
pre-commit install
```

## License

[GPL-3.0](license.txt) © WizardLabz
