# Event Bus Rule

A rule answers one question: *when this document event happens, what should be published and where?*

It binds a **Reference DocType** and an **Event Type** to a **Message Template** and one or more **Destinations**. When a matching document event fires, the payload is rendered once and one Outbox Message is written per destination.

## Fields

| Field | Type | Purpose |
|---|---|---|
| `rule_name` | Data | Primary key; the rule's name. |
| `enabled` | Check | Disabled rules are skipped entirely. |
| `reference_doctype` | Link → DocType | Which doctype's events to listen to. |
| `event_type` | Select | One of the five lifecycle events below. |
| `condition` | Code | Optional Python expression; blank means "always match". |
| `message_template` | Link → Event Bus Message Template | The payload to render. |
| `deduplication_key_template` | Data | Optional Jinja expression recorded on each outbox message. |
| `description` | Small Text | Free-text note for humans. |
| `destinations` | Table → Event Bus Rule Destination | Where to publish. At least one is required to produce anything. |

## Event types

Exactly five events are wired, via a wildcard `doc_events` hook on `"*"`:

| Event | Fires when |
|---|---|
| `after_insert` | A document is created. |
| `on_update` | A document is saved after creation. |
| `on_submit` | A submittable document is submitted. |
| `on_cancel` | A submitted document is cancelled. |
| `on_trash` | A document is deleted. |

A rule matches one event type only. To publish on both create and update, make two rules pointing at the same template.

The bus's own doctypes are excluded from event handling, so rules never fire recursively on Outbox Messages, Delivery Attempts, Rules, Templates, or Settings.

## Conditions

A condition is a Python expression evaluated through `frappe.safe_eval` with `doc` in scope:

```python
doc.variant_of and not doc.disabled
```

```python
doc.grand_total > 1000
```

Available globals are deliberately narrow — `doc`, plus `frappe.utils`:

```python
frappe.utils.getdate(doc.transaction_date).year == 2026
```

A blank or whitespace-only condition matches every document. A condition that raises is treated as a non-match, and the error is logged rather than surfaced to the user saving the document.

## Deduplication key

`deduplication_key_template` is a Jinja expression rendered against the same context as the payload:

```jinja
{{ doc.name }}-{{ context.event_type }}
```

The result is stored on the Outbox Message and passed to the provider in the published message.

**It is recorded, not enforced.** Nothing in the core checks it for uniqueness or suppresses a second message carrying the same key — there is no unique index and no lookup. Treat it as a correlation value you hand to the broker or to downstream consumers so *they* can deduplicate. Enforced deduplication arrives with the Inbox in v0.3.

## Failure isolation

`handle_event` never raises into the saving document's transaction. If rule matching, condition evaluation, or template rendering fails, the error goes to the error log and the user's save completes normally. A broken rule cannot block business operations.

Publishing itself happens after the transaction commits — see [Outbox](outbox.md).

## Related

- [Message Templates](message-templates.md) — what gets rendered
- [Destinations](destinations.md) — where it goes
- [Outbox](outbox.md) — how delivery is made durable
