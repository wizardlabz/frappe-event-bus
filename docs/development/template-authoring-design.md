# Template Authoring & Form Layout — Design

**Date:** 2026-08-02
**Status:** Approved, not yet implemented
**Repos:** `frappe_event_bus`, `frappe_event_bus_rabbitmq`

## Problem

Two independent complaints about the desk UI.

**Authoring a Message Template is unassisted.** `jinja_template` is a bare Code
field. To publish a Sales Order you type every field by hand, from memory,
with no field list, no types, and no warning when you reference a field that
does not exist. The template is not bound to a doctype, so nothing can help
you — the doctype binding lives on Event Bus Rule (`reference_doctype`), one
level up.

That decoupling is correct for an event bus. A template is a message contract,
not a document form: one `order-changed-v1` can serve Sales Order and Purchase
Order, which is why `version` and `message_type` sit on the template. But it
leaves three gaps:

1. No design-time validation of field references.
2. `example_context` is hand-typed JSON that never sees a real document, so it
   cannot catch drift. `validate()` swallows render failures with a msgprint
   (`event_bus_message_template.py:52-57`).
3. No autocomplete.

**Config-heavy doctypes are a single long scroll.** RabbitMQ Destination has
21 fields, Outbox Message 23, RabbitMQ Connection 17. Section breaks group
them but everything is on one page, so primary configuration and rarely-touched
tuning compete for the same attention.

## Constraints from existing code

- `render_payload(template, context, json_schema)` renders Jinja via
  `frappe.render_template`, then **`json.loads` the result** and raises
  `TemplateRenderError` if it does not parse (`rendering.py:60-63`). Any
  generated template must produce valid JSON for arbitrary field values.
- Render context is `{"doc": <live Document>, "context": {"event_type": ...}}`
  (`rule_engine.py:89`). Child tables are reachable as `doc.<fieldname>`.
- `api.preview_payload(message_template, reference_doctype, reference_name)`
  already renders against a real document, surfaced by a Vue 3 dialog in
  `public/js/payload_preview.bundle.js` (wired at `hooks.py:256`). Vue-in-a-
  bundle is the established client pattern.
- Frappe has no grandchild tables, so the field tree is exactly two levels.

## Non-goals

- Link expansion (emitting `customer_name` alongside `customer`).
- Regeneration or staleness detection when a doctype changes.
- Per-field output-key renaming.
- Any second payload-building path at runtime. `render_payload` stays the only
  one.

---

## 1. Data model

**Event Bus Message Template** gains exactly one field:

| Field | Type | Notes |
|---|---|---|
| `applies_to_doctype` | Link → DocType | **Nullable.** Blank = generic template, reusable as today. |

No new doctypes, no child tables, no stored field selection.

**Event Bus Rule** gains a validation, not a field:

- On save, if the linked template's `applies_to_doctype` is set and differs
  from `rule.reference_doctype`, throw.
- `get_query` on the `message_template` Link filters to
  `applies_to_doctype in (reference_doctype, "")`.

This removes the "wrong template on wrong rule" failure class, which today
surfaces only at render time, in a background job, after the user's save has
committed.

## 2. Generator (server)

New module `frappe_event_bus/template_builder.py`. No doctype or DB coupling
in the pure functions, so they unit-test directly — the discipline already used
in `rendering.py`.

```python
def build_field_tree(doctype: str) -> dict
def generate_jinja(doctype: str, selection: dict) -> str
```

`build_field_tree` walks `frappe.get_meta(doctype).fields` two levels deep and
classifies each field:

| Rule | Treatment |
|---|---|
| `Password` | **Excluded, not selectable.** Publishing credentials to a broker is a leak. RabbitMQ Connection has one. |
| Section Break, Column Break, Tab Break, HTML, Button, Heading, Fold | Omitted entirely |
| `permlevel > 0` | Excluded, selectable with explicit opt-in |
| `_user_tags`, `_comments`, `_assign`, `_liked_by`, `amended_from` | Excluded, selectable |
| `Attach`, `Attach Image` | Included but flagged — private files are not fetchable by the consumer, so the URL is a broken reference |
| everything else | Included |

`generate_jinja` emits an envelope-plus-data shape. Metadata lives in the body
as well as (not instead of) `headers_template`, so it survives a transport that
drops headers or a future provider with none:

```jinja
{
  "event": {
    "type": {{ context.event_type | json }},
    "doctype": {{ doc.doctype | json }},
    "name": {{ doc.name | json }},
    "timestamp": {{ frappe.utils.now() | json }}
  },
  "data": {
    "customer": {{ doc.customer | json }},
    "grand_total": {{ doc.grand_total | json }},
    "items": [
      {%- for row in doc.items %}
      {
        "item_code": {{ row.item_code | json }},
        "qty": {{ row.qty | json }}
      }
      {{- "," if not loop.last }}
      {%- endfor %}
    ]
  }
}
```

### `| json` is load-bearing

Every value goes through Frappe's built-in `json` filter, which is
`frappe.as_json` (registered in `frappe/utils/jinja.py:set_filters`). It emits
the bare JSON value — quoting, escaping, `null` — with no surrounding quotes in
the template. Naive interpolation produces invalid JSON the moment a value
contains `"`, a newline, or a backslash, and `render_payload` rejects it at
`json.loads`.

**Not Jinja's `tojson`.** Verified against a live site: `tojson` raises
`TypeError: Object of type datetime is not JSON serializable` on any Date or
Datetime field, which rules it out for a generator. `frappe.as_json` routes
through Frappe's `json_handler` and serializes `datetime`, `date`, `timedelta`
and `Decimal` correctly. `frappe.as_json` is also *not* reachable as
`{{ frappe.as_json(...) }}` — the `frappe` namespace exposed to templates is a
restricted proxy. The filter is the only route.

The existing test fixture has the naive-interpolation bug latent:

```python
'{"todo": "{{ doc.name }}", "priority": "{{ doc.priority }}"}'   # test_integration.py:26
```

It passes only because the fixture data is clean. Verified against a live site:
the same shape with a value containing `"` raises
`TemplateRenderError: Rendered payload is not valid JSON`.

### Frappe escapes HTML before the bus ever sees it

Verified end to end: a ToDo saved with `<tag> & 'apos'` is stored as
`&lt;tag&gt; &amp; 'apos'`. Frappe sanitizes on save — for `Text Editor` *and*
plain `Data` fields — so the escaped form is what is in the database and
therefore what gets published. The generator transmits the stored value
faithfully; it does not add escaping of its own.

Consumers receive HTML-escaped text for any field a user typed markup into.
That is a property of the source data, not of this feature, but it is the kind
of thing that looks like a payload bug when you first see it downstream.

### Missing fields fail silently

Verified: `doc.<nonexistent>` renders as `[]`, not an error — Frappe's
`Document.__getattr__` treats unknown attributes as empty child tables. A
template referencing a field that was later deleted emits `[]` rather than
raising. Generation reads live meta so this cannot happen at authoring time,
but it is the failure mode if a doctype changes afterwards.

### Snapshot semantics

Generated Jinja is a snapshot. It does not silently grow when someone adds a
field to the doctype later — good for safety, at the cost of going stale.
Detecting staleness is a non-goal here.

## 3. Picker (client)

New `template_builder.bundle.js`, Vue 3, mirroring `payload_preview.bundle.js`.
Adds an **Insert from DocType** button to the Message Template form.

The dialog shows a two-level checkbox tree. Everything selectable is ticked by
default — "give me everything as a starting point" is the intended default, and
pruning is the expected next step. Excluded rows render greyed with their
reason.

A live footer, recomputed as you tick:

> Sends 47 fields across 3 child tables. 2 excluded as sensitive.

A computed count is actionable in a way static warning text is not.

Insert offers **at cursor** or **replace entire template**.

### The template is always editable

There is one artifact — `jinja_template` — and it is never read-only. The
picker writes into it and then has no further relationship with it. No mode
switch, no one-way door, no stored selection shadowing the text. After insert
it is ordinary Jinja: rename keys, add computed values, delete lines.

The cost, accepted: no round-trip. Unticking a field later means editing text.
There is also no queryable record of which templates publish a given field —
that answer lives in Jinja source.

Doctype source is `applies_to_doctype` when set; otherwise the dialog asks.

## 4. Preview refinement

The existing preview dialog takes `reference_doctype` and `reference_name` as
two free-text inputs. With `applies_to_doctype` set, the doctype becomes a
fixed label and the name becomes a proper Link picker. A change to the existing
bundle, not new construction.

## 5. Rule integration

Client script on Event Bus Rule: quick-entry on the `message_template` Link
prefills `applies_to_doctype` from `frm.doc.reference_doctype`, so a template
created inline from a rule arrives pre-bound and the picker works immediately.

## 6. Tab layout

Tab Break fields inserted above existing Section Breaks. Sections keep working
as visual grouping inside each tab; no fields move between doctypes and no
fieldnames change.

### `frappe_event_bus`

**Event Bus Message Template**
- *Template* — template_name, applies_to_doctype, message_type, version,
  enabled, description, jinja_template
- *Validation & Preview* — json_schema, example_context, example_output

**Event Bus Rule**
- *Rule* — rule_name, enabled, reference_doctype, event_type, condition,
  message_template
- *Destinations* — destinations (needs the full width)
- *Advanced* — deduplication_key_template, description

**Event Bus Outbox Message** — read-only operational data, so tabs optimize for
scanning, not input flow. Delivery last, because that is where you land when
something failed.
- *Message* — status, event_rule, message_template, provider, connection,
  destination, routing_key, reference_doctype, reference_document, event_type,
  deduplication_key
- *Payload* — payload, headers
- *Delivery* — attempt_count, next_retry_at, published_at, last_error

### `frappe_event_bus_rabbitmq`

**RabbitMQ Event Bus Connection**
- *Connection* — connection_name, enabled, host, port, virtual_host, username,
  password
- *Advanced* — tls_enabled, tls_verify, connection_timeout, heartbeat, notes

**RabbitMQ Event Bus Destination**
- *Destination* — destination_name, connection, exchange, exchange_type,
  routing_key
- *Topology* — declare_exchange, durable_exchange, queue_name, declare_queue,
  durable_queue, bind_queue
- *Publishing* — persistent_message, publisher_confirms, headers_template,
  notes

## 7. Testing

**Unit, no DB** (`template_builder` against a synthetic meta):

- `Password` never appears in the tree as selectable.
- `permlevel > 0` and Frappe internals are excluded but selectable.
- Layout fieldtypes are omitted.
- Child tables nest exactly one level.
- **The one that matters:** generated Jinja, rendered with values containing
  `"`, newlines, backslashes, `None`, `datetime` and `date`, must survive
  `render_payload`'s `json.loads`. The datetime cases are what rule out
  Jinja's `tojson`, so they are the regression guard on the filter choice.

**Integration:**

- Generate for a real doctype, publish through the rule engine, assert the
  payload parses and the envelope carries the right event type.
- Rule save throws when `applies_to_doctype` conflicts with `reference_doctype`.
- Rule save succeeds when the template is generic (`applies_to_doctype` blank).

## Sequencing

The tab work is independent of the template work and can ship first. Both
repos need a branch and a PR; the RabbitMQ tab changes are the only thing
touching `frappe_event_bus_rabbitmq`.
