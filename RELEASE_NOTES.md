# Release Notes

All notable changes to **Frappe Event Bus** (core) are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [Semantic Versioning](https://semver.org/). Provider apps track the core's **major** version — see [version compatibility](docs/concepts/providers.md#version-compatibility).

Sections used: **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**, **Security**.

---

## [Unreleased]

### Added

**Consumer ingestion (broker → Frappe, Phase A)**

- **Event Bus Consumer** — a configured subscription to one source on one broker connection. Ships with `enabled = 0`; nothing is polled until a consumer is switched on by hand.
- **Dispatcher** — a `* * * * *` cron entry polls every enabled consumer whose own `poll_interval` has elapsed, claiming it with a single conditional `UPDATE` so an overrunning cycle cannot poll the same consumer concurrently. A stale claim (older than three poll intervals) can be taken over, so a worker killed mid-cycle cannot strand its consumer.
- **Inbox persistence** — accepted messages are committed to the **Event Bus Inbox Message** table *before* any of them are acknowledged back to the broker. A crash in between means the broker redelivers a message already stored; deduplication records the redelivery as `Ignored` rather than losing or double-storing it. Redelivery is normal operation in this design, not a failure.
- **Deduplication** — enforced by a unique index on `deduplication_key`, not a lookup-then-insert. Five strategies (`Payload Hash`, `External Message ID`, `Header Value`, `Payload Field`, `Custom Expression`), with `Payload Hash` as the default because it is the only strategy guaranteed to produce a key. Every strategy falls back to it when it cannot — including when the body is valid JSON but not an object (`[1, 2, 3]`, `"hello"`), and when the computed key is too long for its 140-character column. `Header Value`, `Payload Field` and `Custom Expression` are refused at save time without a `deduplication_key_expression`, which would otherwise degrade silently to the payload hash. Scope is global across the Inbox, not per consumer; a `Custom Expression` key can include `{{ consumer.name }}` to opt back into per-consumer scoping.
- **Message-type detection** — four modes (`Payload Field`, `Header`, `Routing Key`, `Fixed`) fill in `message_type` on each Inbox row; an undetectable type is left blank rather than rejecting the message.
- **Oversized-message handling** — messages over `max_payload_bytes` (1 MiB default) are rejected from the broker without requeue and never reach the Inbox.

### Notes and limitations

- **Messages are persisted and nothing acts on them.** No handler runs, and no ERPNext document is created or modified by this feature — that is the entire scope of this phase. Of the seven statuses declared on the Inbox, only `Received` and `Ignored` are ever set; `Processing`, `Processed`, `Retry Scheduled`, `Failed`, and `Dead Lettered` exist on the schema for a later processing phase.
- **`Dedicated Worker` consumption mode is rejected.** The field offers it alongside `Scheduled Polling`, but saving a consumer with it throws — only polling is implemented.
- **No live broker implementation ships in this repo.** The consume contract (`ConsumeSession`, `per_message` acknowledgement) is defined here, but no provider app implements it yet; polling is exercised in tests against an in-memory fake provider only.

---

## [0.1.0] — Publisher MVP *(not yet released)*

The first release. Publishes durable, observable, replayable business events from Frappe and ERPNext to a message broker, with no custom code.

Scope is deliberately one direction: **Frappe → broker**. Consuming is designed but not built; it lands in 0.3.0.

### Added

**Rules and events**

- **Event Bus Rule** — binds a Reference DocType and Event Type to a Message Template and one or more destinations.
- All five lifecycle events wired through a wildcard `doc_events` hook: `after_insert`, `on_update`, `on_submit`, `on_cancel`, `on_trash`.
- Optional **conditions** — Python expressions evaluated through `frappe.safe_eval` with `doc` and `frappe.utils` in scope.
- Optional **deduplication key template**, rendered onto each outbox message and passed to the provider. Recorded as a correlation value; not enforced as a uniqueness constraint.
- The bus's own doctypes are excluded from event handling, so rules cannot fire recursively.

**Message templates**

- **Event Bus Message Template** — reusable Jinja templates rendering to JSON.
- JSON Schema validation over a dependency-free subset: `type`, `required`, and nested `properties`. An unrecognised `type` is rejected rather than silently ignored.
- **Staged preview** reporting which step failed — `render`, `json`, `schema_invalid`, or `schema` — so a broken schema is distinguishable from a payload that violates a valid one.
- **Field picker** (`Insert from DocType`) generating a complete envelope template, including child tables, with correct `| json` filters.
- Optional `applies_to_doctype` binding, cross-checked against rules that use the template.

**Delivery**

- **Outbox** — the payload is rendered once per rule and written as one Outbox Message per destination, so a failure against one broker cannot affect another.
- Publishing runs after the triggering transaction commits. A slow or unreachable broker never blocks or rolls back a user's save.
- **Atomic claiming** via a single conditional `UPDATE`, so the post-commit job and the scheduled worker cannot both deliver the same message.
- **Per-message savepoints**, so one failing message cannot take down the rest of the batch.
- **Destination priority**, copied onto the outbox message and applied as `ORDER BY priority ASC, creation ASC`. Copied rather than joined because rows created in one transaction can share a creation timestamp.
- **Exponential backoff** — `base × 2^(attempt-1)`, clamped to 24 hours.
- Failure classification separating **`Failed`** (retryable, attempts exhausted) from **`Dead Lettered`** (provider reported a retry as pointless).
- **Event Bus Delivery Attempt** records per attempt: timings measured on a monotonic clock, error text, and the provider's response.
- **Replay** from any terminal status, with a fresh retry budget.
- **Retention** — a daily purge bounded to `Published` and `Cancelled` messages only. Failed, Dead Lettered, and Retry Scheduled rows are kept regardless of age, so retention never destroys evidence of an unresolved problem.

**Providers**

- **Provider registry** resolving the `event_bus_providers` hook, cached per request. The core imports no broker library.
- **`EventBusProvider`** interface with `publish`, `test_publish`, `validate_connection`, and `validate_destination`, plus the normalized `publish_success` / `publish_failure` result contract.

**Configuration and API**

- **Event Bus Settings** — enabled, delivery logging, max publish attempts, retry backoff, worker batch size, retention days.
- Scheduled jobs: `process_outbox` every five minutes, `purge_outbox` daily.
- Six whitelisted endpoints: `test_publish`, `preview_payload`, `get_field_tree`, `generate_template`, `replay_outbox_message`, `render_example_output`.
- Vue-based desk UI for payload preview, template building, and a Connections tab.

**Project**

- CI running a real Frappe stack — MariaDB and Redis services, `bench init`, `bench new-site` — with no framework mocking.
- pre-commit configuration: ruff, prettier, eslint.
- Full documentation under [`docs/`](docs/index.md), including a verified [getting-started tutorial](docs/getting-started.md).

### Security

- **Every whitelisted endpoint now authorizes its caller.** `@frappe.whitelist()` exposes a function over `/api/method/...` to any authenticated user regardless of what the desk renders, and three endpoints checked nothing.

  The most serious was `preview_payload`: `reference_doctype` and `reference_name` both came from the caller, `frappe.get_doc` performs no permission check of its own, and the rendered payload was returned. Any signed-in user could name a template and an arbitrary document and read its fields back out of the render. `replay_outbox_message` allowed any signed-in user to re-fire messages at external systems, and `render_example_output` exposed template contents.

  Authorization now runs through `frappe.has_permission` against the doctype each endpoint touches, so a site's own permission model stays authoritative. `preview_payload` additionally verifies read permission on the reference document — access to a template does not confer access to the data it renders.

- The three endpoints that previously used `frappe.only_for` moved to the same mechanism. `only_for` returns early when `frappe.flags.in_test` is set, so those guards could not be covered by a test; `has_permission` has no such bypass.

### Notes and limitations

- **The deduplication key is not enforced.** It is rendered, stored, and handed to the provider, but nothing checks it for uniqueness. Enforced deduplication arrives with the Inbox in 0.3.0.
- **The `Cancelled` and `Replayed` statuses are unreachable.** Both are declared on the outbox status field and handled where they appear, but no code path assigns them.
- **No consumer.** Broker → Frappe is designed in the plan but not implemented.
- **No connection pooling.** Providers open a connection per publish, which suits scheduled publishing volumes and is revisited alongside the dedicated worker mode in 0.4.0.
- APIs may still change before 1.0.

[Unreleased]: https://github.com/wizardlabz/frappe-event-bus/compare/main...HEAD
[0.1.0]: https://github.com/wizardlabz/frappe-event-bus/releases/tag/v0.1.0
