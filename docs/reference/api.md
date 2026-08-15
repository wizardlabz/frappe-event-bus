# API Reference

Six whitelisted methods. They exist to serve the desk UI, but they are callable from any Frappe API client.

| Method | Dotted path | Role check |
|---|---|---|
| `test_publish` | `frappe_event_bus.api.test_publish` | System Manager |
| `get_field_tree` | `frappe_event_bus.api.get_field_tree` | System Manager |
| `generate_template` | `frappe_event_bus.api.generate_template` | System Manager |
| `preview_payload` | `frappe_event_bus.api.preview_payload` | none |
| `replay_outbox_message` | `frappe_event_bus.publisher.replay.replay_outbox_message` | none |
| `render_example_output` | `...doctype.event_bus_message_template.event_bus_message_template.render_example_output` | none |

> **Note on permissions.** Only the first three call `frappe.only_for("System Manager")`. The other three rely on Frappe's standard doctype permissions, which for a whitelisted function is a weaker guarantee than an explicit role check. If you expose this site's API to semi-trusted users, review these three before doing so. Tightening them is tracked for v0.2 hardening.

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
