# Getting Started

Publish your first message: a ToDo, from Frappe to RabbitMQ, in about ten minutes.

`ToDo` is used because it exists on every Frappe site and needs no master data. Everything here applies unchanged to `Item`, `Sales Order`, or any other doctype.

## Before you start

- The core and the [RabbitMQ provider](https://github.com/wizardlabz/frappe-event-bus-rabbitmq) installed — see [installation](installation.md)
- A reachable RabbitMQ broker

For a local broker:

```bash
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

The management UI is at <http://localhost:15672> (`guest` / `guest`). Keep it open — it is how you will confirm the message arrived.

---

## 1. Enable the bus

Open **Event Bus Settings** and tick **Enabled**.

The bus ships off. Until this is on, the rule engine returns immediately and no outbox rows are created no matter how many rules exist. This is the single most common reason a first attempt appears to do nothing.

Leave the other fields at their defaults.

## 2. Create a connection

New **RabbitMQ Event Bus Connection**:

| Field | Value |
|---|---|
| Connection Name | `Local Broker` |
| Enabled | ✓ |
| Host | `localhost` (or the broker's hostname) |
| Port | `5672` |
| Virtual Host | `/` |
| Username | `guest` |
| Password | `guest` |

Save, then press **Test Connection**. It opens a real connection and closes it again — a success here means the credentials and network path work.

If this fails, fix it before continuing; nothing downstream can work without it. See [troubleshooting](https://github.com/wizardlabz/frappe-event-bus-rabbitmq/blob/main/docs/troubleshooting.md).

## 3. Create a destination

New **RabbitMQ Event Bus Destination**:

| Field | Value |
|---|---|
| Destination Name | `Tutorial Direct` |
| Connection | `Local Broker` |
| Exchange | `erpnext.tutorial` |
| Exchange Type | `direct` |
| Routing Key | `todo.created` |
| Declare Exchange | ✓ |
| Durable Exchange | ✓ |
| Queue Name | `erpnext.tutorial` |
| Declare Queue | ✓ |
| Durable Queue | ✓ |
| Bind Queue | ✓ |
| Persistent Message | ✓ |
| Publisher Confirms | ✓ |

The three declare/bind boxes let the provider create the exchange and queue for you, so you do not have to set up broker topology by hand. In production you would normally provision topology separately and leave these off.

**Publisher Confirms** is off by default but worth enabling here. Without it a publish to an unrouted exchange succeeds silently, and "it worked but nothing arrived" is a confusing way to start.

Save, then press **Test Publish**. You should get a success result, and the RabbitMQ UI should show one message in `erpnext.tutorial`.

## 4. Create a message template

New **Event Bus Message Template**:

| Field | Value |
|---|---|
| Template Name | `Tutorial ToDo Message` |
| Enabled | ✓ |
| Applies To DocType | `ToDo` |

Jinja Template:

```jinja
{
  "message_type": "TodoCreated",
  "id": {{ doc.name | json }},
  "description": {{ doc.description | json }},
  "status": {{ doc.status | json }},
  "event": {{ context.event_type | json }}
}
```

Two names are in scope: `doc` (the triggering document) and `context` (bus metadata, currently just `context.event_type`).

Pipe every value through `| json`. It produces a correctly quoted and escaped JSON literal and renders empty values as `null`. Without it, a description containing an apostrophe or a newline produces a payload that will not parse.

With **Applies To DocType** set, the **Insert from DocType** picker offers the doctype's fields and generates the template for you.

Save, then use **Preview Payload** to check it renders.

## 5. Create a rule

New **Event Bus Rule**:

| Field | Value |
|---|---|
| Rule Name | `Tutorial ToDo Created` |
| Enabled | ✓ |
| Reference DocType | `ToDo` |
| Event Type | `after_insert` |
| Message Template | `Tutorial ToDo Message` |
| Condition | *(leave blank — matches every ToDo)* |

Add one row to **Destinations**:

| Field | Value |
|---|---|
| Enabled | ✓ |
| Provider | `rabbitmq` |
| Connection | `Local Broker` |
| Destination | `Tutorial Direct` |
| Routing Key | `todo.created` |

Save.

## 6. Trigger it

Create a ToDo — any description will do.

Open **Event Bus Outbox Message**. There should be one new row, holding your rendered payload:

```json
{
  "message_type": "TodoCreated",
  "id": "aeln8gipvn",
  "description": "Tutorial: first event bus message",
  "status": "Open",
  "event": "after_insert"
}
```

It starts as `Pending` and becomes `Published` within seconds. The rule engine enqueues the worker as soon as your save commits; a scheduled job every five minutes is the backstop.

Note what did *not* happen: your save was never blocked by the broker. Publishing runs after the transaction commits, so a slow or unreachable broker cannot slow down or roll back saving a document.

## 7. Confirm delivery

Open the outbox message. Status `Published`, one attempt, no error.

Open **Event Bus Delivery Attempt** for the per-attempt record — timing and the provider's response:

```json
{"exchange": "erpnext.tutorial", "routing_key": "todo.created", "confirmed": true}
```

Now check RabbitMQ at <http://localhost:15672> → **Queues** → `erpnext.tutorial`. Use **Get messages** to read it. The properties confirm what was published:

```
routing_key : todo.created
properties  : {"delivery_mode": 2, "content_type": "application/json"}
```

`delivery_mode: 2` is the persistent flag — the message survives a broker restart, because the queue is durable too.

---

## When nothing happens

Work down this list in order; the first two account for most cases.

| Symptom | Check |
|---|---|
| No outbox row at all | Is **Enabled** ticked in Event Bus Settings? |
| Row stuck in `Pending` | Is the scheduler running? `bench --site <site> doctor`, then `enable-scheduler` |
| Row stuck in `Pending` | Are background workers running? `bench start` in development |
| No row, bus enabled | Does the rule's Reference DocType and Event Type match what you did? A rule on `on_update` does not fire on create. |
| No row, bus enabled | Is the rule Enabled, and does it have at least one Enabled destination? |
| `Failed` | Retryable error, attempts exhausted. Read `last_error`. |
| `Dead Lettered` | Non-retryable — usually credentials or missing exchange. Read `last_error`, fix, then **Replay**. |
| Published, but nothing in the queue | Routing key matches no binding. With `direct`, the key must match exactly. Enable Publisher Confirms to make this fail loudly. |

## Next steps

- [Event Rules](concepts/event-rules.md) — conditions, and the five lifecycle events
- [Message Templates](concepts/message-templates.md) — child tables, JSON Schema validation
- [Destinations](concepts/destinations.md) — publishing one event to several brokers, with priority
- [Retry and Replay](concepts/retry-and-replay.md) — what happens when a broker is down
- [Examples](examples.md) — complete real-world integrations
