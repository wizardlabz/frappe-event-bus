# Event Bus Settings

A single doctype holding global configuration. Find it at **Event Bus Settings** in the desk. Changes are tracked.

| Field | Type | Default | Effect |
|---|---|---|---|
| `enabled` | Check | `0` | Master switch. While off, no rules are evaluated and no outbox rows are created. |
| `enable_delivery_logging` | Check | `1` | Write an Event Bus Delivery Attempt row per publish attempt. |
| `max_publish_attempts` | Int | `5` | Attempts before a retryable failure becomes `Failed`. |
| `retry_backoff_seconds` | Int | `60` | Base for exponential backoff. |
| `worker_batch_size` | Int | `50` | Max messages selected per worker pass. |
| `retention_days` | Int | `30` | Age after which succeeded messages are purged. `0` disables purging. |

## enabled

The bus ships **off**. Until you switch this on, saving documents creates no outbox rows no matter how many rules exist — the rule engine returns immediately.

This is the first thing to check when a rule appears to do nothing. It also gates the retention job, which is a no-op while the bus is disabled.

## enable_delivery_logging

On by default. Turning it off keeps delivery working but stops recording attempt history, so you lose the per-attempt timings, errors, and provider responses used to debug failures. Worth doing only under real write pressure.

## max_publish_attempts

Counts attempts per message. When a retryable failure occurs on the final permitted attempt, the message becomes `Failed` rather than being rescheduled.

A non-retryable failure ignores this entirely and dead-letters on the spot.

Falls back to `5` if blank or zero.

## retry_backoff_seconds

Base interval for `delay = base × 2 ^ (attempt - 1)`, clamped to a 24-hour ceiling.

Set to `0` for no delay — the message becomes due immediately, though it still waits for the next worker pass. Falls back to `60` if blank.

## worker_batch_size

How many due messages one worker pass claims. Larger batches mean fewer passes and more work per transaction. Falls back to `50` if blank or zero.

Because each message runs inside its own savepoint, a large batch does not risk one bad message taking the others down.

## retention_days

Age threshold for purging, measured against `modified`.

Only `Published` and `Cancelled` messages are ever purged. `Failed`, `Dead Lettered`, and `Retry Scheduled` rows survive indefinitely, so retention never removes the record of a problem you have not resolved.

Delivery Attempt rows for purged messages are deleted first, leaving no orphans. `0` or blank disables purging.

## Scheduled jobs

Two jobs, registered by the app:

| Schedule | Job | Purpose |
|---|---|---|
| `*/5 * * * *` | `publisher.retry.process_outbox` | Drain due messages and retries. |
| daily | `publisher.retention.purge_outbox` | Purge aged-out succeeded messages. |

Publishing does not depend solely on the cron: the rule engine also enqueues the worker immediately after the triggering transaction commits, so a healthy message normally publishes within seconds. The cron is the safety net for retries and anything the enqueue missed.

Both require the Frappe scheduler to be running. If messages sit in `Pending`, confirm the scheduler is enabled for the site:

```bash
bench --site <site> doctor
bench --site <site> enable-scheduler
```

## Not yet available

The plan lists further settings — a default retry policy, a default queue, payload-preview and replay toggles, and a default consumption mode. None exist today. The six fields above are the complete set.
