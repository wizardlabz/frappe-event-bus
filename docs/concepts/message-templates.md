# Message Template

A template is a reusable Jinja document that renders to JSON. Templates are separate from rules so the same payload contract can be published by several rules, and so the contract can be reviewed and validated on its own.

## Fields

| Field | Type | Purpose |
|---|---|---|
| `template_name` | Data | Primary key. |
| `enabled` | Check | Disabled templates should not be referenced by active rules. |
| `applies_to_doctype` | Link → DocType | Optional binding; powers the field picker and cross-checks rules. |
| `description` | Small Text | Free-text note. |
| `jinja_template` | Code | The template itself. Must render to valid JSON. |
| `json_schema` | Code | Optional schema the rendered payload is validated against. |
| `example_context` | Code | Sample context used by Preview. |
| `example_output` | Code | Last generated preview output. |

## Writing a template

The context contains two names:

- `doc` — the document that triggered the event
- `context` — bus metadata; currently `context.event_type`

```jinja
{
  "message_type": "UpdateVariantMessage",
  "name": {{ doc.name | json }},
  "item_code": {{ doc.item_code | json }},
  "brand": {{ doc.brand | json }},
  "disabled": {{ doc.disabled | int }},
  "event": {{ context.event_type | json }},
  "modified": {{ doc.modified | json }}
}
```

### Always use the `json` filter

Pipe every interpolated value through `| json`. It emits a correctly quoted and escaped JSON literal, and it renders `None` as `null`.

Without it, a value containing a quote, backslash, or newline produces a payload that will not parse — and a value that is `None` renders as the bare word `None`, which is not JSON.

```jinja
"description": {{ doc.description | json }}     ✅ handles quotes, newlines, null
"description": "{{ doc.description }}"          ❌ breaks on any quote or newline
```

Jinja's built-in `tojson` also works, and some published examples use it. Prefer `json`: it is Frappe's `as_json`, which serialises Frappe types such as `datetime`, `date`, and `Decimal` that plain `tojson` cannot handle.

Frappe HTML-escapes field values before they reach the template, so characters like `&` and `<` may appear escaped in the payload. This is Frappe behaviour, not a bus transformation.

### Child tables

Iterate as normal, minding trailing commas:

```jinja
"items": [
  {% for row in doc.items %}
  {
    "item_code": {{ row.item_code | json }},
    "qty": {{ row.qty }}
  }{% if not loop.last %},{% endif %}
  {% endfor %}
]
```

An empty child table renders `[]`.

## The field picker

With `applies_to_doctype` set, the template form offers **Insert from DocType**: a tree of the doctype's fields — including child tables — from which you select what to publish. It generates a complete envelope template with the correct `| json` filters, which you can then edit by hand.

Two API methods back this: `get_field_tree` and `generate_template`. See [API reference](../reference/api.md).

## JSON Schema validation

`json_schema` is optional. When present, the rendered payload is validated against it.

The validator implements a deliberate subset of JSON Schema with no third-party dependency:

- `type` — `object`, `array`, `string`, `number`, `integer`, `boolean`, `null`
- `required` — a list of property names
- `properties` — nested schemas, recursively

Anything else is not enforced. An unrecognised `type` is rejected outright rather than ignored, because a silently skipped constraint would leave a schema that appears to pass while validating nothing.

`boolean` is excluded from `number` and `integer` — Python's `bool` subclasses `int`, and accepting `true` where a number is required would be a false pass.

```json
{
  "type": "object",
  "required": ["message_type", "name"],
  "properties": {
    "message_type": { "type": "string" },
    "disabled": { "type": "integer" }
  }
}
```

## Preview

**Preview Payload** renders the template against `example_context` and reports each stage separately, because the three failure modes need different fixes:

| Stage | Meaning |
|---|---|
| `render` | The template itself failed to render — bad Jinja, missing attribute. |
| `json` | It rendered, but the output is not valid JSON — usually a missing `| json`. |
| `schema_invalid` | The **schema** is malformed, so nothing could be checked against it. |
| `schema` | Payload and schema are both fine, but the payload violates the schema. |

`schema_invalid` and `schema` are distinguished on purpose: one means fix your schema, the other means fix your payload.

## On the publish path

Publishing uses the raising counterpart of the preview renderer. A template that fails to render, produces invalid JSON, or violates its schema stops that message rather than publishing something malformed. The failure is logged and the triggering document's save is unaffected.

## Not yet available

The plan describes `message_type` and `version` fields on the template. Neither exists today — express the message type as a field inside the payload, as the examples do.

## Related

- [Event Rules](event-rules.md) — what triggers a render
- [API reference](../reference/api.md) — `preview_payload`, `get_field_tree`, `generate_template`, `render_example_output`
