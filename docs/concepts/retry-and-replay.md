# Retry, Replay, and Retention

## Retryable vs non-retryable

Providers return a normalized result. The `retryable` flag decides what happens next:

```python
{"success": True,  "provider_message_id": "...", "response": {}}
{"success": False, "error": "Connection refused", "retryable": True}
{"success": False, "error": "ACCESS_REFUSED",     "retryable": False}
```

| Result | Outcome |
|---|---|
| Success | `Published`, `published_at` stamped, `last_error` cleared. |
| Retryable, attempts remaining | `Retry Scheduled` with `next_retry_at` set. |
| Retryable, attempts exhausted | `Failed`. |
| Not retryable | `Dead Lettered` immediately, regardless of attempts left. |

If a provider raises an exception instead of returning a result, the worker catches it, logs the traceback, and treats it as a **retryable** failure. An unexpected provider bug therefore degrades into a retry rather than silently dropping a message.

## Backoff

Delay is exponential in the attempt number:

```
delay = retry_backoff_seconds × 2 ^ (attempt - 1)
```

clamped to a ceiling of 24 hours. With the default 60-second base:

| Attempt | Delay |
|---|---|
| 1 | 60s |
| 2 | 2m |
| 3 | 4m |
| 4 | 8m |
| 5 | 16m |

A `retry_backoff_seconds` of `0` or less produces no delay, making the message due immediately.

Because the worker runs every 5 minutes, a computed delay shorter than the cron interval does not mean the retry happens sooner — the message becomes *eligible* at `next_retry_at` and is picked up on the next pass.

## Attempt budget

`max_publish_attempts` in Event Bus Settings caps retries; it defaults to 5 when unset. The count is per message, tracked in `attempt_count`.

## Delivery attempts

When `enable_delivery_logging` is on (the default), every attempt writes an **Event Bus Delivery Attempt** row:

| Field | Contents |
|---|---|
| `outbox_message` | The message this attempt belongs to. |
| `attempt_number` | 1-based. |
| `provider` | Provider name. |
| `started_at` / `completed_at` | Wall-clock bounds. |
| `duration_ms` | Measured on a monotonic clock, so it is unaffected by clock adjustments. |
| `success` | Whether the provider reported success. |
| `error_message` | The failure text, or empty on success. |
| `provider_response` | The provider's response payload, JSON-encoded. |

Turning logging off skips these rows entirely. You keep delivery but lose the audit trail — useful only under genuine write pressure.

## Replay

Replay resets a terminal message and queues it again with a **fresh retry budget**:

```python
frappe.call("frappe_event_bus.publisher.replay.replay_outbox_message", name="EB-OUT-00042")
```

It sets `status` back to `Pending`, clears `next_retry_at`, `last_error`, and `published_at`, resets `attempt_count` to `0`, and enqueues the worker after commit.

Replayable statuses are `Failed`, `Dead Lettered`, `Published`, `Cancelled`, and `Replayed`. Attempting to replay a message in any other status — `Pending`, `Publishing`, `Retry Scheduled` — throws, because those are already in flight and replaying them would risk a double delivery.

`Published` is replayable on purpose: re-sending a message a consumer lost is a legitimate operation. It does mean replay can produce duplicates downstream, so consumers should be idempotent.

## Retention

A daily scheduled job purges aged-out messages, bounding table growth.

Only **successful terminal states** are purged: `Published` and `Cancelled`. `Failed`, `Dead Lettered`, and `Retry Scheduled` rows are kept regardless of age — retention exists to stop the table growing without bound, not to destroy the evidence you need when a delivery goes wrong.

- Age is measured on `modified`, not `creation`.
- Delivery Attempt rows are deleted first, so nothing is left pointing at a missing message.
- `retention_days` of `0` or blank disables purging entirely.
- The job is a no-op while the bus is disabled.

## Related

- [Outbox](outbox.md) — statuses and the worker
- [Settings reference](../reference/settings.md) — every knob named above
