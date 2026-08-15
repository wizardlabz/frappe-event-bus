# Examples

Complete, ready-to-import integrations live in their own repository:

**[wizardlabz/frappe-event-bus-examples](https://github.com/wizardlabz/frappe-event-bus-examples)**

Each example ships the exact Message Template, Event Bus Rule, and RabbitMQ connection/destination configuration as importable JSON, alongside a README explaining when it fires and what it publishes.

| Example | Scenario |
|---|---|
| [01 — Item update → POS](https://github.com/wizardlabz/frappe-event-bus-examples/tree/main/examples/01-item-update-to-pos) | Publish a compact "variant updated" message on every enabled Item variant update, broadcast to any number of consumers through a **fanout** exchange. |
| [02 — Sales Order submitted → Analytics](https://github.com/wizardlabz/frappe-event-bus-examples/tree/main/examples/02-sales-order-submitted-to-analytics) | Publish a full Sales Order on submit to a **topic** exchange, so analytics consumers subscribe by routing-key pattern such as `sales_order.#`. |
| [03 — Delivery Note submitted → Queue](https://github.com/wizardlabz/frappe-event-bus-examples/tree/main/examples/03-delivery-note-to-queue) | Publish a Delivery Note on submit straight to a durable declared queue via a **direct** exchange — for a single consumer, with the queue created and bound automatically. |

The repository also includes `scripts/install_examples.py` for loading an example into a site.

## Why a separate repository

The examples version independently of the core and the providers, and they are the one place where core configuration, provider configuration, and broker topology appear together. Keeping them separate means there is exactly one copy of each rule and template rather than a duplicate here that drifts out of date.

## Using an example

1. Install the core and the [RabbitMQ provider](installation.md).
2. Enable the bus in **Event Bus Settings**.
3. Create the connection and destination the example describes, and confirm them with **Test Connection** and **Test Publish**.
4. Import or hand-create the Message Template and Event Bus Rule from the example's JSON.
5. Save a matching document and watch **Event Bus Outbox Message**.

If a message does not appear, work through the [getting started](getting-started.md) checks — the bus being disabled and an idle scheduler account for most cases.

## Contributing an example

Open a pull request against the examples repository. A good example is a real scenario, states which doctype and event it binds to, includes the condition, and ships the exact JSON rather than a prose description.
