# API Reference

Six whitelisted methods. They exist to serve the desk UI, but they are callable from any Frappe API client.

| Method | Dotted path | Permission required |
|---|---|---|
| `test_publish` | `frappe_event_bus.api.test_publish` | read on the provider connection **and** destination |
| `get_field_tree` | `frappe_event_bus.api.get_field_tree` | write on Event Bus Message Template |
| `generate_template` | `frappe_event_bus.api.generate_template` | write on Event Bus Message Template |
| `preview_payload` | `frappe_event_bus.api.preview_payload` | read on the template, **and** read on the reference document |
| `replay_outbox_message` | `frappe_event_bus.publisher.replay.replay_outbox_message` | write on the outbox message |
| `render_example_output` | `...doctype.event_bus_message_template.event_bus_message_template.render_example_output` | read on the template |

## How authorization works

`@frappe.whitelist()` exposes a function to every authenticated user over `/api/method/...`, regardless of what the desk chooses to render. Hiding a button is not access control, so each endpoint checks permission itself.

Checks go through `frappe.has_permission` against the doctype the endpoint actually touches, rather than a hardcoded role. Your permission model stays authoritative: grant a custom role access to the Event Bus doctypes and the API follows automatically, with no code change.

Two consequences worth knowing:

- **Access to a template does not confer access to the data it renders.** `preview_payload` takes a caller-supplied `reference_doctype` and `reference_name`, so it verifies read permission on that specific document before rendering it. Being allowed to read a template is not permission to read every document you could point it at.
- **`test_publish` checks the connection it resolves to, not just the destination.** A caller cannot reach a connection indirectly through a destination they happen to be able to see.

Because these are document-level checks, User Permissions apply — a role with blanket read on a doctype can still be restricted to particular documents, and these endpoints honour that.

---

## test_publish

Publish a one-off payload through a provider without creating a rule or an outbox message. This is what the **Test Publish** button calls.

```python
frappe.call(
    "frappe_event_bus.api.test_publish",
    provider="rabbitmq",
    connection="Local Broker",
    destination="POS Fanout",
    payload={"hello": "world"},
    headers={"x-source": "manual-test"},   # optional
)
```

`payload` and `headers` accept either a dict or a JSON string. Returns the provider's normalized result — `{"success": true, "provider_message_id": ..., "response": {...}}` or `{"success": false, "error": ..., "retryable": ...}`.

Nothing is persisted. A failure here does not create an outbox row or a delivery attempt.

## preview_payload

Render a message template and report which stage succeeded.

```python
frappe.call(
    "frappe_event_bus.api.preview_payload",
    message_template="UpdateVariantMessage",
    reference_doctype="Item",     # optional
    reference_name="ITEM-0001",   # optional
)
```

With `reference_doctype` and `reference_name`, it renders against that real document with `context.event_type` set to `"preview"`. Without them, it renders against the template's stored `example_context`.

Returns the staged report:

| Key | Meaning |
|---|---|
| `ok` | Everything passed. |
| `rendered` | The Jinja template rendered without error. |
| `json_valid` | The output parsed as JSON. |
| `schema_present` | A schema was configured. |
| `schema_parsed` | The schema itself is well-formed and enforceable. |
| `schema_valid` | The payload satisfies the schema. `null` when there is no usable schema. |
| `output` | The rendered string. |
| `parsed` | The parsed payload. |
| `stage` | Which step failed: `render`, `json`, `schema_invalid`, or `schema`. |
| `error` | Human-readable failure text. |
| `valid` | Mirror of `ok`, kept for backwards compatibility. |

## get_field_tree

Return the field picker tree for a doctype — its own fields plus one level of child tables.

```python
frappe.call("frappe_event_bus.api.get_field_tree", doctype="Item")
```

## generate_template

Turn a picker selection into a complete Jinja envelope with correct `| json` filters.

```python
frappe.call(
    "frappe_event_bus.api.generate_template",
    doctype="Item",
    selection={"fields": ["item_code", "brand"], "children": {"attributes": ["attribute"]}},
)
```

`selection` accepts a dict or a JSON string. Returns the generated template as a string; it does not save anything.

## replay_outbox_message

Reset a terminal message to `Pending` with a fresh retry budget and enqueue the worker.

```python
frappe.call(
    "frappe_event_bus.publisher.replay.replay_outbox_message",
    name="EB-OUT-00042",
)
```

Valid from `Failed`, `Dead Lettered`, `Published`, `Cancelled`, and `Replayed`. Throws for `Pending`, `Publishing`, or `Retry Scheduled`, which are already in flight.

Returns `{"name": ..., "status": "Pending"}`.

## render_example_output

Render a template's stored example context. Simpler than `preview_payload` — it returns only a pass/fail rather than the staged report.

```python
frappe.call(
    "...event_bus_message_template.render_example_output",
    template_name="UpdateVariantMessage",
)
```

Returns `{"valid": true, "output": "...", "parsed": {...}}` or `{"valid": false, "error": "..."}`.

## Related

- [Message Templates](../concepts/message-templates.md) — what preview is checking
- [Retry and Replay](../concepts/retry-and-replay.md) — what replay resets
