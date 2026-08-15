# Consumers

An **Event Bus Consumer** is a configured subscription to one source on one broker connection — a RabbitMQ queue is the only source type any shipped provider actually reads from. A dispatcher polls it on a schedule, and whatever the broker hands back is written to the **Inbox** (`Event Bus Inbox Message`), deduplicated against everything already stored there.

That is the whole of what this feature does. **Nothing acts on a message once it is in the Inbox.** No handler runs against it, no ERPNext document is created or updated, and no field on the Inbox row beyond identity, payload, and headers is ever populated. Turning an Inbox message into something that changes data is a later, unbuilt phase — this one only gets messages safely out of the broker and into a table.

## Consumers ship disabled

`enabled` defaults to `0` on every new Event Bus Consumer. A consumer you have just created polls nothing until you switch it on by hand in the desk. This is deliberate: consuming means pulling from someone else's queue and writing rows on every poll, so a newly configured — and possibly misconfigured — consumer must never start doing that by accident.

## Flow

```
dispatcher (cron, every minute)
   ↓
enabled consumers whose poll_interval has elapsed → claim → open a consume session
   ↓
receive a batch (up to consumer.batch_size, default 25)
   ↓
for each message:
   too large (max_payload_bytes)?  → reject, no requeue, dropped — no Inbox row
   otherwise                       → persist to Inbox as Received, or as Ignored if a duplicate
   ↓  (commit — every accepted message is now durable)
acknowledge every accepted message back to the broker
```

## Persist, commit, then acknowledge

`poll_consumer` in `frappe_event_bus/consumer/worker.py` persists and commits every accepted message *before* it acknowledges any of them. That ordering is the whole correctness argument, and it has one consequence worth internalising: **redelivery is normal, not an error.**

If a worker crashes between the commit and the acknowledgement, the broker never saw an ack, so it delivers the same message again on the next poll. The consumer has no way to tell the broker "I already have this" except by recognising it — which is exactly what deduplication does. The redelivered message is written to the Inbox again, the unique index rejects the second insert, and the row is recorded as a duplicate with status `Ignored`. There is no ordering in which a message is acknowledged but not stored, and there is no ordering in which a crash silently loses a message either — the worst case is a message you already have arriving once more.

An oversized message (over `max_payload_bytes`, 1 MiB by default) is handled differently: it is rejected from the broker with `requeue=False` and never reaches the Inbox at all. Nothing here records that it happened — there is no log entry and no persisted row — so an oversized message is invisible to this app once dropped. `max_payload_bytes = 0` disables the check.

## Claiming a consumer for one poll cycle

The dispatcher (`poll_due_consumers`) runs every minute via a cron scheduler event and looks at every enabled consumer. Each consumer carries its own `poll_interval` (seconds, default 60); `is_due()` compares it against `last_polled_at` and skips consumers that aren't due yet, so a one-minute dispatcher doesn't force every consumer onto a one-minute cadence.

Claiming works the same way outbox claiming does: a single conditional `UPDATE` sets `claimed_at`, and only the caller whose update actually changed a row proceeds. If a worker dies mid-poll, the claim would otherwise strand the consumer forever — `claimed_at` older than three poll intervals is treated as abandoned and can be reclaimed. `release_consumer` clears the claim and stamps `last_polled_at` whether the poll succeeded or raised, so one unreachable broker never stops the dispatcher from moving on to the next consumer.

## Deduplication

Deduplication is enforced by a **unique index on `deduplication_key`**, not by checking for an existing row first — a check-then-insert would race two pollers against the same key. The insert either succeeds or raises `UniqueValidationError`/`DuplicateEntryError`, and the raise *is* the duplicate detection: the row is re-inserted with `status = Ignored`, `deduplication_key` cleared to `NULL` (so many duplicates can coexist without violating the index), and `duplicate_key` / `duplicate_of` pointing back at the original.

`consumer.deduplication_strategy` picks how the key is computed:

| Strategy | Key source |
|---|---|
| **Payload Hash** *(default)* | SHA-256 of the exact received body (`payload_raw`). |
| External Message ID | The broker's own message id, if the provider supplies one. |
| Header Value | A named header, via `deduplication_key_expression`. |
| Payload Field | A top-level field of the parsed payload, via `deduplication_key_expression`. |
| Custom Expression | A Jinja expression over `payload`, `headers`, and `consumer`. |

Payload Hash is the default because it is the only strategy guaranteed to produce a key. RabbitMQ does not guarantee a message carries an id, a header, or any particular payload field, and every other strategy falls back to the payload hash whenever it cannot produce one — a null or empty key would silently disable deduplication for that message, and there is no safe way to fail open in a system where redelivery is expected.

"Cannot produce one" includes a body that is valid JSON but not an object: `[1, 2, 3]` and `"hello"` are both legal to publish and neither has a named field to read. Nothing about a message is allowed to make it unpersistable — a message that cannot be written is never acknowledged, so the broker redelivers it every cycle forever and no operator action can clear it. The same rule covers a key that is simply too long: `deduplication_key`, `ordering_key` and `message_type` are 140-character columns, so a Custom Expression concatenating two fields can overflow one. An over-long deduplication key falls back to the payload hash, an over-long ordering key falls back to the deduplication key, and an over-long message type is dropped to empty rather than truncated into a plausible wrong answer.

`Header Value`, `Payload Field` and `Custom Expression` all read `deduplication_key_expression`, so the consumer's `validate()` refuses to save any of them without one. Left blank they would not fail — they would look up the empty string, find nothing, and quietly deduplicate on the payload hash instead, which under the global scope described below discards genuinely distinct messages that share a body.

### Scope is global, not per consumer

The unique index is on the Inbox as a whole, across every consumer. If two consumers are both subscribed to the same upstream event and would compute the same key — the default Payload Hash naturally does this when the body is identical — the second consumer's copy is written as `Ignored`, not processed, even though it belongs to a different consumer with a different purpose. Deduplication scope is a property of the key, not of the consumer.

The escape hatch is to make the key consumer-specific. With **Custom Expression**, include the consumer in the template:

```
{{ consumer.name }}-{{ payload.id }}
```

This is the only strategy that has access to `consumer` in its expression context, so it's the only way to opt back into per-consumer scoping.

### Key expressions fail closed

Jinja key expressions (used by Custom Expression, and by the ordering key below) run through `frappe_event_bus/consumer/expressions.py`, which exists specifically to avoid two traps that would otherwise let two unrelated messages collide on the same key: `frappe.render_template` renders an unresolved variable as the literal text `"{{ no such element: ... }}"` instead of raising, and a payload parsed into `frappe._dict` returns `None` instead of raising `AttributeError` on a missing field, which Jinja then renders as the literal string `"None"`. Either failure mode would produce an identical key across messages that don't actually match. `render_key_expression` treats a blank expression, a render error, an unresolved `{{ ... }}` left in the output, or an empty result as equally unusable — all return `None`, and every strategy that uses it falls back to the payload hash rather than accept a key that isn't trustworthy.

## Message type detection

`consumer.message_type_detection` decides how `message_type` is filled in on the Inbox row:

| Mode | Behaviour |
|---|---|
| **Payload Field** *(default)* | Reads `message_type_source` (default `message_type`) as a top-level key of the parsed payload. |
| Header | Reads `message_type_source` as a header name. |
| Routing Key | Uses the message's routing key directly; `message_type_source` is ignored. |
| Fixed | Uses `message_type_source` itself as a literal value for every message. |

When the source field or header is missing — or the payload is not an object at all, or the detected value is too long for the column — `detect_message_type` returns `None` rather than raising. A message the broker already delivered is still persisted, with an empty `message_type`, rather than rejected over a routing detail. Deciding what to do about an undetectable type is left for the processing phase.

## Statuses

The Inbox status field declares seven values, because the schema is built for the processing phase this ingestion phase does not implement:

| Status | Set today? | Meaning |
|---|---|---|
| `Received` | Yes | Persisted, unique, nothing has acted on it. |
| `Ignored` | Yes | A duplicate by deduplication key; recorded, not processed. |
| `Processing` | No | Reserved for the processing phase. |
| `Processed` | No | Reserved for the processing phase. |
| `Retry Scheduled` | No | Reserved for the processing phase. |
| `Failed` | No | Reserved for the processing phase. |
| `Dead Lettered` | No | Reserved for the processing phase. |

Only `Received` and `Ignored` are ever assigned by any code path today. The other five exist on the field so that a later phase adds behaviour against an already-correct schema rather than requiring a migration.

## What isn't implemented

- **Dedicated Worker consumption mode.** The field offers `Scheduled Polling` and `Dedicated Worker`, but the controller's `validate()` throws if you save a consumer with `Dedicated Worker` — only polling exists.
- **Processing.** No handler, no ERPNext document creation or update, nothing that reads `message_type` to decide what a message means. `target_doctype`, `target_document`, `handler`, `last_error`, and `processed_at` are all schema with no writer.
- **`ordering_key`.** Computed and stored on every row (falling back to the deduplication key), but nothing reads it back. It exists for a future phase to serialize processing on.
- **A live consume session against a real broker.** This repo defines the contract (`frappe_event_bus/consumer/contract.py` — a `ConsumeSession` protocol and a `per_message` acknowledgement contract) and the dispatcher that drives it, but no provider app in this codebase implements it yet. Polling is exercised in tests against an in-memory fake provider only; a working RabbitMQ consume session is separate, unbuilt work in the provider repo.

## Related

- [The Outbox](outbox.md) — the equivalent durability layer for the opposite direction, Frappe → broker
- [Providers](providers.md) — how a provider is registered and resolved
