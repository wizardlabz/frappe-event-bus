# Destinations

A destination is a child row on an Event Bus Rule. It says *which broker, over which connection, to what target*. One rule can carry many destinations, and each gets its own Outbox Message so one broker being down never blocks another.

## Fields

| Field | Type | Purpose |
|---|---|---|
| `enabled` | Check | Disabled rows are skipped; no outbox message is created. |
| `provider` | Data | Registered provider name, e.g. `rabbitmq`. |
| `connection` | Data | Name of a provider connection document. |
| `destination` | Data | Name of a provider destination document. |
| `routing_key` | Data | Optional override of the destination's own routing key. |
| `priority` | Int | Publish order; lower goes first. Defaults to `0`. |
| `headers_template` | Code | Optional Jinja template rendering a JSON object of headers. |

`provider`, `connection`, and `destination` are plain Data fields rather than Links, because the documents they name live in provider apps that may not be installed. The core stores the names and resolves them at publish time through the [provider registry](providers.md).

## One row per destination

When a rule matches, the payload is rendered **once** and copied to one Outbox Message per enabled destination:

```
Item updated
  └─ rule matched, payload rendered once
       ├─ Outbox Message → rabbitmq / pos-exchange
       ├─ Outbox Message → rabbitmq / search-exchange
       └─ Outbox Message → kafka / analytics
```

Each row retries, fails, and replays independently.

## Priority

Priority is copied from the destination row onto the outbox message at creation, and the worker selects with `ORDER BY priority ASC, creation ASC`.

Ordering is ascending — **lower publishes first**. `0` is the default and therefore the highest priority unless you use negative numbers.

The value is copied rather than joined at query time deliberately: rows created inside a single transaction can share a creation timestamp, so ordering by creation alone would not reliably separate them.

Priority orders the *batch the worker selects*. It is not a real-time guarantee — a message that becomes due later is not retroactively placed ahead of one already published.

## Headers

`headers_template` renders to a JSON object, using the same context as the payload:

```jinja
{
  "x-source": "erpnext",
  "x-doctype": {{ doc.doctype | json }},
  "x-event": {{ context.event_type | json }}
}
```

The rendered object is stored on the outbox message and handed to the provider, which maps it onto broker-native headers.

If the template renders to something that is not valid JSON, or to a JSON value that is not an object, headers fall back to `{}` and the problem is logged. A bad headers template degrades the message; it does not stop it.

## Routing key

A destination row's `routing_key` overrides the routing key on the provider's own destination document. Leave it blank to use the provider default. This lets one shared destination document serve several rules that differ only in routing key.

## Related

- [Providers](providers.md) — how `provider`/`connection`/`destination` are resolved
- [Outbox](outbox.md) — what happens after rows are created
- [RabbitMQ destination fields](https://github.com/wizardlabz/frappe-event-bus-rabbitmq/blob/main/docs/destination.md)
