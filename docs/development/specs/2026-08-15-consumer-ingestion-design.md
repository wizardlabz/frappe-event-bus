# Design — Consumer Ingestion (v0.3, Phase A)

**Status:** approved, not implemented
**Date:** 2026-08-15
**Scope:** broker → Inbox. Inbox → ERPNext is Phase B and has its own spec.

---

## 1. Why this is split

v0.3 in the project plan is four doctypes, a polling worker, deduplication, per-key ordering, two provider consume contracts, an inbound RabbitMQ consumer, and three handler action types. Built as one unit, none of it is testable until nearly all of it exists.

The Inbox is a natural seam:

```
broker ──▶ [ INGESTION ] ──▶ Inbox ──▶ [ PROCESSING ] ──▶ ERPNext documents
           Phase A (this spec)         Phase B
```

Phase A can be verified against a live broker with no handlers — messages land as `Received` and stop. Phase B can be verified against hand-inserted Inbox rows with no broker at all. Splitting also front-loads the risky part: broker semantics, acknowledgement, and redelivery are settled before any business logic depends on them.

Phase A is also the safest possible half to ship first. Nothing it does can create or modify an ERPNext document.

## 2. The correctness rule

One ordering constraint governs the whole design:

**Persist the message and commit before acknowledging the broker.**

```
open consume session
  receive_batch(n)
  for each message:
      compute dedup key → detect duplicate
      insert Inbox row (Received | Ignored)
  COMMIT                          ◀── durability boundary
  for each message: ack
close session
```

The three possible crash points:

| Crash | Broker state | Inbox state | Outcome |
|---|---|---|---|
| Before commit | unacked | nothing written | Broker redelivers. Clean. |
| After commit, before ack | unacked | row written | Broker redelivers. Dedup records it `Ignored`. |
| After ack | acked | row written | Normal completion. |

There is no ordering in which a message is acknowledged but not stored. Redelivery is therefore **normal operation**, not an error path — which is why deduplication is mandatory rather than optional.

## 3. Consume contract

### Correction to the plan

The plan sketches `receive_batch(consumer_doc, max_messages)` and `acknowledge(consumer_doc, provider_message)` as independent calls. That cannot work for RabbitMQ: **delivery tags are scoped to the channel that delivered them**, so acknowledging on a freshly opened channel is invalid. The existing publisher opens and closes a connection per call, which is correct for publishing and wrong for consuming.

The contract is therefore a **session** spanning receive through acknowledge:

```python
with provider.consume_session(consumer_doc) as session:
    messages = session.receive(max_messages)
    # ... persist and commit ...
    for message in messages:
        session.ack(message)
```

### Core interface

```python
class ConsumeSession:
    """One connection/channel lifetime. Receive and ack share it."""

    def receive(self, max_messages: int) -> list[dict]: ...
    def ack(self, message: dict) -> None: ...
    def reject(self, message: dict, requeue: bool = False) -> None: ...
```

`receive` returns normalized dicts, mirroring how the publisher receives a normalized message:

```python
{
    "provider_message_id": str | None,   # broker id, if the broker assigns one
    "payload_raw": str,                  # exact bytes decoded as UTF-8
    "payload": dict | None,              # parsed, None when not valid JSON
    "headers": dict,
    "routing_key": str | None,
    "source": str,                       # queue / topic the message came from
    "raw_metadata": dict,                # provider-specific, stored for diagnosis
    "_handle": object,                   # provider-private (e.g. delivery tag)
}
```

`_handle` is opaque to the core and never persisted. It exists so `ack`/`reject` can identify the message to the broker.

### Contract dispatch

Providers declare `consume_contract` in their spec. The worker dispatches on it:

```python
contract = spec.get("consume_contract", "per_message")
if contract != "per_message":
    raise NotImplementedError(
        f"Consume contract {contract!r} is not supported yet."
    )
```

Only `per_message` is implemented. `batch_commit` (Kafka and other offset-based brokers) is a v0.4 concern; the dispatch point exists so adding it is a branch rather than a rewrite of the loop. No `BatchCommitConsumeMixin` is written until something implements it.

### RabbitMQ implementation

Polling mode uses batched `basic.get`, per the plan. A session opens one connection and one channel, issues up to `batch_size` `basic.get` calls, and holds the channel open until the worker has committed and acknowledged.

`ack` maps to `basic_ack(delivery_tag)`. `reject` maps to `basic_nack(delivery_tag, requeue=...)`.

## 4. Deduplication

### Scope

**Global across the Inbox.** A deduplication key identifies a message regardless of which consumer received it.

Consequence, accepted deliberately: two consumers legitimately subscribed to the same upstream event — one creating a Sales Order, one sending a notification — will see the second copy recorded `Ignored` and never processed. Under global scope that is the defined semantics, not a defect.

The escape hatch is the key expression, which has `consumer` in scope. Writing `{{ consumer.name }}-{{ payload.order_id }}` restores per-consumer behaviour where a deployment needs it. The scope itself is not configurable — one rule, with a documented way out.

### Enforcement

Uniqueness is enforced by a **UNIQUE index** on `Event Bus Inbox Message.deduplication_key`, not by a read-then-write check.

A read-then-write races: two pollers can both find the key absent and both insert. That race occurs precisely in the scenario global scope exists to handle, so it must be closed properly. With a unique index the insert either succeeds or raises, and the raise *is* the detection:

```python
try:
    row = _insert_inbox_row(consumer, message, dedup_key, status="Received")
except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
    original = frappe.db.get_value(
        "Event Bus Inbox Message", {"deduplication_key": dedup_key}, "name"
    )
    row = _insert_inbox_row(
        consumer, message, dedup_key=None,
        status="Ignored", duplicate_of=original,
    )
```

Duplicate rows store `duplicate_of` and leave `deduplication_key` NULL, so many duplicates coexist under the unique index while originals stay unique. MySQL and MariaDB permit multiple NULLs in a unique index; the key is echoed into the non-indexed `duplicate_key` field so it stays visible in the UI.

### Strategies

| Strategy | Key source |
|---|---|
| External Message ID | the broker's message id, when it assigns one |
| Header Value | a named header |
| Payload Field | a named field in the parsed payload |
| Payload Hash *(default)* | SHA-256 of `payload_raw` |
| Custom Expression | a Jinja expression |

Payload Hash is the default because it is the only strategy that always yields a key. RabbitMQ does not guarantee a message id exists unless the publisher set one, so External Message ID cannot be the default.

The Custom Expression context is `{"payload": ..., "headers": ..., "consumer": ...}`. An expression rendering to empty or whitespace falls back to the payload hash rather than producing a null key, so a misconfigured expression cannot disable deduplication.

## 5. DocTypes

### Event Bus Consumer

| Field | Type | Default | Notes |
|---|---|---|---|
| `consumer_name` | Data | — | Primary key |
| `enabled` | Check | `0` | Ships disabled |
| `provider` | Data | — | Registered provider name |
| `connection` | Data | — | Provider connection docname |
| `source_type` | Select | `RabbitMQ Queue` | `RabbitMQ Queue`, `Kafka Topic`, `NATS Subject`, `Redis Stream` |
| `source` | Data | — | Queue / topic / subject / stream name |
| `consumption_mode` | Select | `Scheduled Polling` | `Dedicated Worker` is rejected on save in this phase |
| `batch_size` | Int | `25` | Max messages per poll |
| `poll_interval` | Int | `60` | Seconds between polls |
| `last_polled_at` | Datetime | — | Read-only |
| `claimed_at` | Datetime | — | Read-only; overlap guard |
| `deduplication_strategy` | Select | `Payload Hash` | See §4 |
| `deduplication_key_expression` | Small Text | — | Required for Header/Payload Field/Custom |
| `ordering_key_expression` | Small Text | — | Stored only; Phase B consumes it |
| `message_type_detection` | Select | `Payload Field` | `Header`, `Payload Field`, `Routing Key`, `Fixed` |
| `message_type_source` | Data | `message_type` | Header name, payload field, or the fixed value |
| `max_payload_bytes` | Int | `1048576` | `0` disables the limit |
| `notes` | Small Text | — | |

`consumption_mode` exists from this phase because the plan requires it, but only `Scheduled Polling` is accepted. Selecting `Dedicated Worker` throws on save with a message naming v0.4, rather than silently doing nothing.

### Event Bus Inbox Message

| Field | Type | Notes |
|---|---|---|
| `consumer` | Link | |
| `provider` / `source` | Data | Copied from the consumer at receive time |
| `external_message_id` | Data | Broker id when present |
| `message_type` | Data | Result of detection |
| `payload` | Code | The exact received string |
| `headers` | Code | JSON |
| `raw_metadata` | Code | Provider-specific diagnostics |
| `status` | Select | See below |
| `deduplication_key` | Data, **unique** | NULL on duplicate rows |
| `duplicate_key` | Data | Key echoed on duplicate rows, not indexed |
| `duplicate_of` | Link → self | Set on duplicate rows |
| `ordering_key` | Data | Stored only in this phase |
| `attempt_count` | Int | Phase B |
| `received_at` | Datetime | |
| `processed_at` | Datetime | Phase B |
| `last_error` | Small Text | Phase B |
| `target_doctype` / `target_document` / `handler` | Data / Data / Link | Phase B |

**Statuses.** The field carries every status from the plan on day one — `Received`, `Processing`, `Processed`, `Retry Scheduled`, `Failed`, `Dead Lettered`, `Ignored` — so Phase B adds behaviour rather than a schema migration.

Phase A only ever assigns **`Received`** and **`Ignored`**. This is documented rather than left implicit: the outbox already carries two statuses (`Cancelled`, `Replayed`) that no code assigns, and that ambiguity should not be repeated silently.

Phase B fields are created now for the same reason, and left null.

## 6. The worker

### Dispatcher

One cron entry, every minute:

```python
def poll_due_consumers() -> dict[str, int]:
    for name in _enabled_consumers():
        consumer = frappe.get_cached_doc("Event Bus Consumer", name)
        if not _is_due(consumer):
            continue
        if not _claim_consumer(name):
            continue          # a previous cycle is still running
        try:
            poll_consumer(name)
        finally:
            _release_consumer(name)
```

`_is_due` compares `now()` against `last_polled_at + poll_interval`. A consumer with no `last_polled_at` is due immediately.

### Claiming

A consumer whose poll cycle outruns its interval must not be polled concurrently — overlapping `basic.get` sessions would fetch the same backlog twice and duplicate work that dedup then has to absorb.

Claiming reuses the conditional-UPDATE pattern already proven in `outbox_worker._claim_message`:

```sql
UPDATE `tabEvent Bus Consumer`
SET claimed_at = %s
WHERE name = %s AND (claimed_at IS NULL OR claimed_at < %s)
```

The second bound is a staleness cutoff (`now - 3 × poll_interval`), so a worker killed mid-cycle cannot strand a consumer permanently. Only the worker whose UPDATE changes a row proceeds.

> **Portability note.** This statement uses MySQL backtick quoting, matching the existing outbox claim. See the CI parity spec — the app currently has no Postgres coverage and this syntax would not run there.

### Poll cycle

```python
def poll_consumer(name: str) -> dict[str, int]:
    consumer = frappe.get_doc("Event Bus Consumer", name)
    provider = get_consume_provider(consumer.provider)   # raises if contract unsupported

    with provider.consume_session(consumer) as session:
        messages = session.receive(consumer.batch_size or 25)
        accepted, rejected = [], []

        for message in messages:
            frappe.db.savepoint("eb_inbox_msg")
            try:
                if _too_large(message, consumer):
                    rejected.append(message)
                    continue
                _persist(consumer, message)
                accepted.append(message)
            except Exception:
                frappe.db.rollback(save_point="eb_inbox_msg")
                frappe.log_error(title="Event Bus: inbox persist failed",
                                 message=frappe.get_traceback())
                # left unacked: the broker will redeliver it

        frappe.db.commit()                    # durability boundary

        for message in accepted:
            session.ack(message)
        for message in rejected:
            session.reject(message, requeue=False)
```

Each message persists inside its own savepoint, matching `process_pending`. A message that fails to persist is simply not acknowledged, so the broker redelivers it — no special-case recovery path.

### Failure isolation

A consumer whose broker is unreachable logs the error and the dispatcher moves to the next consumer. One dead broker must not stop every other consumer's poll.

Oversized messages are rejected **without requeue** and recorded, so a single giant message cannot wedge the loop by being redelivered forever.

## 7. Security

- Consumers ship **disabled** (`enabled` defaults to `0`).
- Any whitelisted endpoint added in this phase calls `frappe.has_permission` against the doctype it touches, per the convention established in the endpoint authorization fix. `frappe.only_for` is not used — it no-ops under `frappe.flags.in_test` and cannot be tested.
- `max_payload_bytes` bounds what a remote sender can push into the database.
- Message-type allowlisting is deliberately **not** in this phase. It gates handler dispatch, which is Phase B. Phase A only persists; no external message can reach an ERPNext document.

## 8. Testing

**Pure units — no broker, no site required**

- Dedup key computation for all five strategies, including the empty-expression fallback to payload hash.
- Message-type detection for all four modes, including a missing header or field.
- `_is_due` boundary behaviour, including a consumer that has never polled.

**Live broker integration — against the CI `rabbitmq:3-management` service**

- Receive a published message and assert an Inbox row appears with the right payload, headers, and routing key.
- Acknowledged messages do not reappear on the next poll.
- A rejected oversized message does not reappear.
- Non-JSON payloads persist with `payload` null and `payload_raw` intact, rather than failing the batch.

**The test that matters most**

Simulate a crash between commit and acknowledgement — persist and commit a batch, skip the ack, then poll again:

```
assert redelivered message produces a second Inbox row
assert its status == "Ignored"
assert its duplicate_of == <the original row>
assert the original row is untouched
```

This asserts §2's correctness claim directly rather than trusting it. Following the provider convention, integration tests do **not** skip when the broker is unreachable — a silent skip reports green on a broken CI broker.

## 9. Out of scope

Handlers, Create/Update/Upsert actions, per-ordering-key serialization, mapping templates, inbox retry/replay/dead-lettering, message-type allowlisting, Kafka, and Dedicated Worker mode.

`ordering_key` is computed and stored in this phase so Phase B can serialize on it without a migration, but nothing reads it.

## 10. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Split of v0.3 | Ingestion first | Each half independently testable; broker risk lands first |
| Duplicate handling | Record as `Ignored` with `duplicate_of` | Redelivery becomes observable; a silent drop makes an ack bug invisible |
| Dedup scope | Global | Chosen over per-consumer; `consumer` in the key expression is the escape hatch |
| Dedup enforcement | UNIQUE index | Read-then-write races exactly where global scope matters |
| Batch-commit contract | Dispatch seam only | Avoids speculative code while keeping Kafka a branch, not a rewrite |
| Poll cadence | Per-consumer via a 1-minute dispatcher | Honours the plan's Poll Interval; a busy queue and a quiet one need different budgets |
| Consume interface | Session-scoped | Delivery tags are channel-scoped; the plan's sketch cannot ack correctly |
