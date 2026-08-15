# The Outbox

The outbox is the durability layer. Nothing is published from inside a document's transaction — the rule engine writes rows, and a background worker delivers them.

## Why

If publishing happened during `doc.save()`, a slow or unreachable broker would slow down or roll back the user's save, and a crash between save and publish would lose the message. Writing an outbox row in the same transaction as the document makes the intent to publish as durable as the business data. Delivery then happens afterwards, at its own pace, with its own retry budget.

## Flow

```
document event
   ↓  (inside the document's transaction)
rule matched → payload rendered once → one Outbox Message per destination, status Pending
   ↓  (after commit)
worker enqueued
   ↓
select due rows → claim → publish → record attempt → advance status
```

Two things drive the worker:

- **After commit** — the rule engine enqueues `process_pending` with `enqueue_after_commit=True`, so a message normally publishes seconds after the save.
- **On a schedule** — a cron entry runs `process_outbox` every 5 minutes, catching anything the post-commit job missed and picking up retries that have come due.

## Statuses

| Status | Meaning |
|---|---|
| `Pending` | Created, waiting to be picked up. |
| `Publishing` | Claimed by a worker, delivery in flight. |
| `Published` | Provider confirmed success. Terminal. |
| `Retry Scheduled` | Retryable failure; `next_retry_at` holds the next attempt time. |
| `Failed` | Retryable, but the attempt budget is exhausted. Terminal. |
| `Dead Lettered` | Provider reported a non-retryable error. Terminal. |
| `Cancelled` | Declared, but never set by any current code path. |
| `Replayed` | Declared, but never set by any current code path. |

The distinction between `Failed` and `Dead Lettered` is worth internalising: **`Failed` means we ran out of tries, `Dead Lettered` means trying again could not possibly help** — bad credentials, an unroutable message, a channel precondition failure. Both are terminal, and both can be replayed by hand.

`Cancelled` and `Replayed` exist in the status list and are handled where they appear (`Cancelled` is purgeable, `Replayed` is replayable), but nothing in the current code assigns them. You will not see them in practice.

## Claiming, and why double-delivery cannot happen

Two workers can run at once — the post-commit job and the 5-minute cron overlap easily. A message is claimed with a single conditional UPDATE:

```sql
UPDATE `tabEvent Bus Outbox Message`
SET status = 'Publishing'
WHERE name = %s AND status IN ('Pending', 'Retry Scheduled')
```

Only the worker whose UPDATE actually changes a row — `rowcount == 1` — proceeds. The row lock blocks the other claimer until the winner's transaction ends, at which point it sees `Publishing` and backs off. There is no window in which both publish.

If the loser is chosen as a deadlock or lock-timeout victim, that is treated as losing the race: it skips the row and lets the winner deliver.

## Batch isolation

Each message is processed inside its own savepoint. An unexpected error on one message rolls back only that message, and the rest of the batch still commits.

Deadlock and timeout errors are the exception — InnoDB has already rolled the whole transaction back, taking the savepoint with it, so the worker records the message as skipped rather than trying to roll back to a savepoint that no longer exists. The row keeps its pre-claim status and the next pass picks it up.

## Selection order

```sql
ORDER BY priority ASC, creation ASC
LIMIT <worker_batch_size>
```

A row is due when its status is `Pending`, or its status is `Retry Scheduled` and `next_retry_at` has passed. Batch size comes from Event Bus Settings and defaults to 50 when unset.

## What the provider receives

The worker hands the provider a normalized dict, independent of any broker:

```python
{
    "outbox_name": "...",
    "provider": "rabbitmq",
    "connection": "...",
    "destination": "...",
    "routing_key": "...",
    "payload": {...},         # parsed
    "payload_json": "{...}",  # raw string
    "headers": {...},
    "reference_doctype": "Item",
    "reference_name": "ITEM-0001",
    "event_type": "on_update",
    "deduplication_key": "...",
}
```

Providers get both the parsed payload and the exact rendered string, so a provider that must publish bytes byte-for-byte can use `payload_json` without a reserialisation round trip.

## Related

- [Retry and Replay](retry-and-replay.md) — what happens after a failure
- [Providers](providers.md) — how the publisher is resolved
- [Settings reference](../reference/settings.md) — batch size, logging, retention
