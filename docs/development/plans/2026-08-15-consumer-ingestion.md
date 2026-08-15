# Consumer Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist messages from a broker into an Inbox table, deduplicated, without ever acknowledging a message that was not stored.

**Architecture:** A scheduled dispatcher polls each due Consumer. For each, the provider opens a consume *session* (one connection and channel), the worker receives a batch, writes one Inbox row per message, commits, and only then acknowledges. Pure logic (deduplication keys, message-type detection) is kept free of database coupling so it unit-tests without a site.

**Tech Stack:** Frappe v15, Python 3.11+, MariaDB. RabbitMQ via `pika` lives in the provider app and is out of scope for this plan.

**Source spec:** `docs/development/specs/2026-08-15-consumer-ingestion-design.md`

## Global Constraints

- Persist and **commit** before acknowledging. No ordering may acknowledge an unstored message.
- Deduplication scope is **global** across the Inbox, enforced by a UNIQUE index — never a read-then-write check.
- Only the `per_message` consume contract is implemented. Any other contract raises `NotImplementedError`.
- Phase A assigns only the `Received` and `Ignored` statuses. All seven statuses exist on the field from the start.
- Consumers ship disabled (`enabled` defaults to `0`).
- Guard any whitelisted endpoint with `frappe.has_permission`, never `frappe.only_for` (it no-ops under `frappe.flags.in_test`).
- Tabs for indentation, matching the existing codebase. Run `ruff format` before every commit.
- Nothing in this plan may create or modify an ERPNext document.

---

## File Structure

| File | Responsibility |
|---|---|
| `frappe_event_bus/consumer/__init__.py` | Package marker |
| `frappe_event_bus/consumer/dedup.py` | Deduplication key computation. Pure — no DB. |
| `frappe_event_bus/consumer/detection.py` | Message-type detection. Pure — no DB. |
| `frappe_event_bus/consumer/contract.py` | `ConsumeSession` protocol, contract dispatch, session resolution |
| `frappe_event_bus/consumer/inbox.py` | Inbox row persistence and duplicate handling |
| `frappe_event_bus/consumer/worker.py` | Due check, claim/release, poll cycle, dispatcher |
| `.../doctype/event_bus_consumer/` | Consumer doctype + controller |
| `.../doctype/event_bus_inbox_message/` | Inbox Message doctype + controller |
| `frappe_event_bus/tests/fake_consume_provider.py` | In-memory consume session for tests |
| `frappe_event_bus/tests/test_dedup.py` | Task 3 tests |
| `frappe_event_bus/tests/test_detection.py` | Task 4 tests |
| `frappe_event_bus/tests/test_inbox.py` | Tasks 2, 6 tests |
| `frappe_event_bus/tests/test_consumer_worker.py` | Tasks 7, 8, 9 tests |

---

## Task 1: Event Bus Consumer doctype

**Files:**
- Create: `frappe_event_bus/frappe_event_bus/doctype/event_bus_consumer/event_bus_consumer.json`
- Create: `frappe_event_bus/frappe_event_bus/doctype/event_bus_consumer/event_bus_consumer.py`
- Create: `frappe_event_bus/frappe_event_bus/doctype/event_bus_consumer/__init__.py`
- Test: `frappe_event_bus/tests/test_consumer_worker.py`

**Interfaces:**
- Produces: DocType `Event Bus Consumer` with fields `consumer_name`, `enabled`, `provider`, `connection`, `source_type`, `source`, `consumption_mode`, `batch_size`, `poll_interval`, `last_polled_at`, `claimed_at`, `deduplication_strategy`, `deduplication_key_expression`, `ordering_key_expression`, `message_type_detection`, `message_type_source`, `max_payload_bytes`, `notes`.

- [ ] **Step 1: Write the failing test**

Create `frappe_event_bus/tests/test_consumer_worker.py`:

```python
"""Consumer configuration and the polling worker."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

CONSUMER = "_Test EB Consumer"


def _make_consumer(**overrides) -> frappe.model.document.Document:
	values = {
		"doctype": "Event Bus Consumer",
		"consumer_name": CONSUMER,
		"provider": "fake",
		"connection": "conn-1",
		"source_type": "RabbitMQ Queue",
		"source": "test.queue",
	}
	values.update(overrides)
	return frappe.get_doc(values).insert(ignore_permissions=True)


class TestConsumerDocType(FrappeTestCase):
	def setUp(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_a_new_consumer_is_disabled(self):
		"""Consuming is sensitive, so it must never switch itself on."""
		consumer = _make_consumer()
		self.assertEqual(consumer.enabled, 0)

	def test_defaults_are_set(self):
		consumer = _make_consumer()
		self.assertEqual(consumer.batch_size, 25)
		self.assertEqual(consumer.poll_interval, 60)
		self.assertEqual(consumer.deduplication_strategy, "Payload Hash")
		self.assertEqual(consumer.max_payload_bytes, 1048576)

	def test_dedicated_worker_mode_is_rejected(self):
		"""The field exists from this phase, but only polling is implemented."""
		with self.assertRaises(frappe.ValidationError):
			_make_consumer(consumption_mode="Dedicated Worker")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: FAIL — `Event Bus Consumer` does not exist.

- [ ] **Step 3: Create the doctype JSON**

Create `event_bus_consumer.json`. Copy the shape of `event_bus_settings.json` (same `module`, `engine`, `sort_field`, `track_changes: 1`) and set `"issingle": 0`, `"autoname": "field:consumer_name"`. Fields, in `field_order`:

```json
{"fieldname": "consumer_name", "fieldtype": "Data", "label": "Consumer Name", "reqd": 1, "unique": 1},
{"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "0"},
{"fieldname": "column_break_main", "fieldtype": "Column Break"},
{"fieldname": "provider", "fieldtype": "Data", "label": "Provider", "reqd": 1},
{"fieldname": "connection", "fieldtype": "Data", "label": "Connection", "reqd": 1},
{"fieldname": "section_break_source", "fieldtype": "Section Break", "label": "Source"},
{"fieldname": "source_type", "fieldtype": "Select", "label": "Source Type",
 "options": "RabbitMQ Queue\nKafka Topic\nNATS Subject\nRedis Stream", "default": "RabbitMQ Queue"},
{"fieldname": "source", "fieldtype": "Data", "label": "Source", "reqd": 1},
{"fieldname": "column_break_source", "fieldtype": "Column Break"},
{"fieldname": "consumption_mode", "fieldtype": "Select", "label": "Consumption Mode",
 "options": "Scheduled Polling\nDedicated Worker", "default": "Scheduled Polling"},
{"fieldname": "section_break_polling", "fieldtype": "Section Break", "label": "Polling"},
{"fieldname": "batch_size", "fieldtype": "Int", "label": "Batch Size", "default": "25"},
{"fieldname": "poll_interval", "fieldtype": "Int", "label": "Poll Interval (seconds)", "default": "60"},
{"fieldname": "column_break_polling", "fieldtype": "Column Break"},
{"fieldname": "last_polled_at", "fieldtype": "Datetime", "label": "Last Polled At", "read_only": 1},
{"fieldname": "claimed_at", "fieldtype": "Datetime", "label": "Claimed At", "read_only": 1},
{"fieldname": "section_break_dedup", "fieldtype": "Section Break", "label": "Deduplication"},
{"fieldname": "deduplication_strategy", "fieldtype": "Select", "label": "Deduplication Strategy",
 "options": "Payload Hash\nExternal Message ID\nHeader Value\nPayload Field\nCustom Expression",
 "default": "Payload Hash"},
{"fieldname": "deduplication_key_expression", "fieldtype": "Small Text", "label": "Deduplication Key Expression"},
{"fieldname": "column_break_dedup", "fieldtype": "Column Break"},
{"fieldname": "ordering_key_expression", "fieldtype": "Small Text", "label": "Ordering Key Expression"},
{"fieldname": "section_break_message", "fieldtype": "Section Break", "label": "Message"},
{"fieldname": "message_type_detection", "fieldtype": "Select", "label": "Message Type Detection",
 "options": "Payload Field\nHeader\nRouting Key\nFixed", "default": "Payload Field"},
{"fieldname": "message_type_source", "fieldtype": "Data", "label": "Message Type Source", "default": "message_type"},
{"fieldname": "column_break_message", "fieldtype": "Column Break"},
{"fieldname": "max_payload_bytes", "fieldtype": "Int", "label": "Max Payload Bytes", "default": "1048576"},
{"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"}
```

Permissions: one row, `System Manager` with `read`, `write`, `create`, `delete`, `share`, `print`, `email` — matching the other doctypes.

- [ ] **Step 4: Write the controller**

Create `event_bus_consumer.py`:

```python
"""Event Bus Consumer controller."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class EventBusConsumer(Document):
	"""A configured source of inbound messages."""

	def validate(self) -> None:
		self._reject_unimplemented_consumption_mode()

	def _reject_unimplemented_consumption_mode(self) -> None:
		"""Fail loudly rather than silently never polling.

		The field carries both modes because the plan defines both, but only
		Scheduled Polling is implemented. A consumer saved as Dedicated Worker
		would otherwise look configured and never receive anything.
		"""
		if self.consumption_mode == "Dedicated Worker":
			frappe.throw(
				frappe._("Dedicated Worker consumption mode is not available yet. Use Scheduled Polling.")
			)
```

Create an empty `__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `bench --site dev.localhost migrate && bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: add Event Bus Consumer doctype"
```

---

## Task 2: Event Bus Inbox Message doctype

**Files:**
- Create: `frappe_event_bus/frappe_event_bus/doctype/event_bus_inbox_message/event_bus_inbox_message.json`
- Create: `frappe_event_bus/frappe_event_bus/doctype/event_bus_inbox_message/event_bus_inbox_message.py`
- Create: `frappe_event_bus/frappe_event_bus/doctype/event_bus_inbox_message/__init__.py`
- Test: `frappe_event_bus/tests/test_inbox.py`

**Interfaces:**
- Produces: DocType `Event Bus Inbox Message`. `deduplication_key` carries `"unique": 1`, which Frappe turns into a real UNIQUE index — this is what makes deduplication race-proof.

- [ ] **Step 1: Write the failing test**

Create `frappe_event_bus/tests/test_inbox.py`:

```python
"""Inbox persistence and duplicate handling."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

CONSUMER = "_Test EB Inbox Consumer"


def _make_row(dedup_key: str | None, **overrides):
	values = {
		"doctype": "Event Bus Inbox Message",
		"consumer": CONSUMER,
		"provider": "fake",
		"source": "test.queue",
		"payload": '{"a": 1}',
		"status": "Received",
		"deduplication_key": dedup_key,
	}
	values.update(overrides)
	return frappe.get_doc(values).insert(ignore_permissions=True)


class TestInboxUniqueness(FrappeTestCase):
	def test_the_same_key_cannot_be_stored_twice(self):
		"""Deduplication is enforced by the database, not by a lookup."""
		_make_row("key-abc")
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			_make_row("key-abc")

	def test_many_rows_may_have_no_key(self):
		"""Duplicate rows store NULL so they coexist under the unique index."""
		first = _make_row(None, status="Ignored")
		second = _make_row(None, status="Ignored")
		self.assertNotEqual(first.name, second.name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_inbox`
Expected: FAIL — `Event Bus Inbox Message` does not exist.

- [ ] **Step 3: Create the doctype JSON**

Same shape conventions as Task 1, with `"autoname": "hash"`. Fields:

```json
{"fieldname": "consumer", "fieldtype": "Link", "label": "Consumer", "options": "Event Bus Consumer"},
{"fieldname": "status", "fieldtype": "Select", "label": "Status",
 "options": "Received\nProcessing\nProcessed\nRetry Scheduled\nFailed\nDead Lettered\nIgnored",
 "default": "Received", "in_list_view": 1},
{"fieldname": "column_break_head", "fieldtype": "Column Break"},
{"fieldname": "provider", "fieldtype": "Data", "label": "Provider"},
{"fieldname": "source", "fieldtype": "Data", "label": "Source"},
{"fieldname": "message_type", "fieldtype": "Data", "label": "Message Type"},
{"fieldname": "section_break_dedup", "fieldtype": "Section Break", "label": "Identity"},
{"fieldname": "external_message_id", "fieldtype": "Data", "label": "External Message ID"},
{"fieldname": "deduplication_key", "fieldtype": "Data", "label": "Deduplication Key", "unique": 1},
{"fieldname": "column_break_dedup", "fieldtype": "Column Break"},
{"fieldname": "duplicate_key", "fieldtype": "Data", "label": "Duplicate Key", "read_only": 1},
{"fieldname": "duplicate_of", "fieldtype": "Link", "label": "Duplicate Of",
 "options": "Event Bus Inbox Message", "read_only": 1},
{"fieldname": "ordering_key", "fieldtype": "Data", "label": "Ordering Key"},
{"fieldname": "section_break_payload", "fieldtype": "Section Break", "label": "Payload"},
{"fieldname": "payload", "fieldtype": "Code", "label": "Payload", "options": "JSON"},
{"fieldname": "headers", "fieldtype": "Code", "label": "Headers", "options": "JSON"},
{"fieldname": "raw_metadata", "fieldtype": "Code", "label": "Raw Metadata", "options": "JSON"},
{"fieldname": "section_break_processing", "fieldtype": "Section Break", "label": "Processing"},
{"fieldname": "attempt_count", "fieldtype": "Int", "label": "Attempt Count", "default": "0"},
{"fieldname": "received_at", "fieldtype": "Datetime", "label": "Received At"},
{"fieldname": "processed_at", "fieldtype": "Datetime", "label": "Processed At"},
{"fieldname": "column_break_processing", "fieldtype": "Column Break"},
{"fieldname": "last_error", "fieldtype": "Small Text", "label": "Last Error"},
{"fieldname": "target_doctype", "fieldtype": "Data", "label": "Target DocType"},
{"fieldname": "target_document", "fieldtype": "Data", "label": "Target Document"},
{"fieldname": "handler", "fieldtype": "Data", "label": "Handler"}
```

`processed_at`, `last_error`, `target_doctype`, `target_document`, `handler`, and `attempt_count` are unused in Phase A. They exist now so Phase B adds behaviour rather than a schema migration.

- [ ] **Step 4: Write the controller**

Create `event_bus_inbox_message.py`:

```python
"""Event Bus Inbox Message controller."""

from __future__ import annotations

from frappe.model.document import Document


class EventBusInboxMessage(Document):
	"""A message received from a broker and persisted before acknowledgement.

	Phase A assigns only ``Received`` and ``Ignored``. The remaining statuses
	exist on the field so the processing phase adds behaviour, not a migration.
	"""

	pass
```

Create an empty `__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `bench --site dev.localhost migrate && bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_inbox`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: add Event Bus Inbox Message doctype with a unique dedup key"
```

---

## Task 3: Deduplication key computation

**Files:**
- Create: `frappe_event_bus/consumer/__init__.py`
- Create: `frappe_event_bus/consumer/dedup.py`
- Test: `frappe_event_bus/tests/test_dedup.py`

**Interfaces:**
- Produces: `compute_dedup_key(consumer, message) -> str`. `consumer` is any object with `deduplication_strategy`, `deduplication_key_expression`, and `name`. `message` is the normalized dict described in the spec.

- [ ] **Step 1: Write the failing test**

Create `frappe_event_bus/tests/test_dedup.py`:

```python
"""Deduplication key computation. Pure — no database."""

from __future__ import annotations

import hashlib

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.consumer.dedup import compute_dedup_key


def _consumer(strategy: str, expression: str | None = None):
	return frappe._dict(
		name="c1",
		deduplication_strategy=strategy,
		deduplication_key_expression=expression,
	)


def _message(**overrides):
	message = {
		"provider_message_id": "amqp-1",
		"payload_raw": '{"order_id": "SO-1"}',
		"payload": {"order_id": "SO-1"},
		"headers": {"x-id": "H-9"},
		"routing_key": "order.created",
	}
	message.update(overrides)
	return message


class TestDedupKey(FrappeTestCase):
	def test_payload_hash_is_the_sha256_of_the_raw_body(self):
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		self.assertEqual(compute_dedup_key(_consumer("Payload Hash"), _message()), expected)

	def test_external_message_id_uses_the_broker_id(self):
		self.assertEqual(compute_dedup_key(_consumer("External Message ID"), _message()), "amqp-1")

	def test_header_value_reads_the_named_header(self):
		key = compute_dedup_key(_consumer("Header Value", "x-id"), _message())
		self.assertEqual(key, "H-9")

	def test_payload_field_reads_the_named_field(self):
		key = compute_dedup_key(_consumer("Payload Field", "order_id"), _message())
		self.assertEqual(key, "SO-1")

	def test_custom_expression_can_scope_the_key_to_the_consumer(self):
		"""The documented escape hatch from global deduplication scope."""
		consumer = _consumer("Custom Expression", "{{ consumer.name }}-{{ payload.order_id }}")
		self.assertEqual(compute_dedup_key(consumer, _message()), "c1-SO-1")

	def test_an_empty_expression_falls_back_to_the_payload_hash(self):
		"""A misconfigured expression must never disable deduplication."""
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		consumer = _consumer("Custom Expression", "{{ payload.missing }}")
		self.assertEqual(compute_dedup_key(consumer, _message()), expected)

	def test_a_missing_broker_id_falls_back_to_the_payload_hash(self):
		expected = hashlib.sha256('{"order_id": "SO-1"}'.encode()).hexdigest()
		message = _message(provider_message_id=None)
		self.assertEqual(compute_dedup_key(_consumer("External Message ID"), message), expected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_dedup`
Expected: FAIL — `No module named 'frappe_event_bus.consumer'`

- [ ] **Step 3: Write the implementation**

Create `frappe_event_bus/consumer/__init__.py` (empty) and `frappe_event_bus/consumer/dedup.py`:

```python
"""Deduplication key computation.

Deliberately free of doctype and database coupling so it unit-tests directly.

Every strategy falls back to the payload hash when it cannot produce a key. A
null or empty key would disable deduplication for that message, and redelivery
is normal operation in this design — so there is no safe way to fail open.
"""

from __future__ import annotations

import hashlib
from typing import Any

import frappe


def payload_hash(message: dict[str, Any]) -> str:
	"""SHA-256 of the exact received body."""
	return hashlib.sha256((message.get("payload_raw") or "").encode()).hexdigest()


def compute_dedup_key(consumer: Any, message: dict[str, Any]) -> str:
	"""Return the deduplication key for ``message`` under ``consumer``'s strategy."""
	strategy = consumer.deduplication_strategy or "Payload Hash"
	expression = (consumer.deduplication_key_expression or "").strip()

	if strategy == "External Message ID":
		candidate = message.get("provider_message_id")
	elif strategy == "Header Value":
		candidate = (message.get("headers") or {}).get(expression)
	elif strategy == "Payload Field":
		candidate = (message.get("payload") or {}).get(expression)
	elif strategy == "Custom Expression":
		candidate = _render_expression(expression, consumer, message)
	else:
		candidate = None

	candidate = str(candidate).strip() if candidate is not None else ""
	return candidate or payload_hash(message)


def _render_expression(expression: str, consumer: Any, message: dict[str, Any]) -> str | None:
	"""Render a Jinja key expression, returning None when it cannot be used."""
	if not expression:
		return None
	context = {
		"payload": message.get("payload") or {},
		"headers": message.get("headers") or {},
		"consumer": consumer,
	}
	try:
		return frappe.render_template(expression, context).strip()
	except Exception:
		frappe.log_error(
			title="Event Bus: deduplication key expression failed",
			message=frappe.get_traceback(),
		)
		return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_dedup`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: compute deduplication keys for all five strategies"
```

---

## Task 4: Message-type detection

**Files:**
- Create: `frappe_event_bus/consumer/detection.py`
- Test: `frappe_event_bus/tests/test_detection.py`

**Interfaces:**
- Produces: `detect_message_type(consumer, message) -> str | None`. `consumer` needs `message_type_detection` and `message_type_source`.

- [ ] **Step 1: Write the failing test**

Create `frappe_event_bus/tests/test_detection.py`:

```python
"""Message-type detection. Pure — no database."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.consumer.detection import detect_message_type


def _consumer(mode: str, source: str | None = None):
	return frappe._dict(message_type_detection=mode, message_type_source=source)


def _message(**overrides):
	message = {
		"payload": {"message_type": "OrderCreated"},
		"headers": {"message_type": "HeaderType"},
		"routing_key": "order.created",
	}
	message.update(overrides)
	return message


class TestMessageTypeDetection(FrappeTestCase):
	def test_payload_field_reads_the_named_field(self):
		self.assertEqual(
			detect_message_type(_consumer("Payload Field", "message_type"), _message()),
			"OrderCreated",
		)

	def test_header_reads_the_named_header(self):
		self.assertEqual(
			detect_message_type(_consumer("Header", "message_type"), _message()), "HeaderType"
		)

	def test_routing_key_uses_the_routing_key(self):
		self.assertEqual(
			detect_message_type(_consumer("Routing Key"), _message()), "order.created"
		)

	def test_fixed_uses_the_configured_value(self):
		self.assertEqual(
			detect_message_type(_consumer("Fixed", "AlwaysThis"), _message()), "AlwaysThis"
		)

	def test_a_missing_field_yields_none_rather_than_raising(self):
		"""An undetectable type is recorded as unknown, not a failed ingest."""
		self.assertIsNone(
			detect_message_type(_consumer("Payload Field", "absent"), _message())
		)

	def test_a_non_json_payload_yields_none(self):
		message = _message(payload=None)
		self.assertIsNone(detect_message_type(_consumer("Payload Field", "message_type"), message))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_detection`
Expected: FAIL — `No module named 'frappe_event_bus.consumer.detection'`

- [ ] **Step 3: Write the implementation**

Create `frappe_event_bus/consumer/detection.py`:

```python
"""Message-type detection.

Returns ``None`` rather than raising when the type cannot be determined. An
undetectable message type is a routing problem for the processing phase to
report, not a reason to reject a message the broker already delivered.
"""

from __future__ import annotations

from typing import Any


def detect_message_type(consumer: Any, message: dict[str, Any]) -> str | None:
	"""Return the message type for ``message`` under ``consumer``'s detection mode."""
	mode = consumer.message_type_detection or "Payload Field"
	source = (consumer.message_type_source or "").strip()

	if mode == "Fixed":
		return source or None
	if mode == "Routing Key":
		return message.get("routing_key") or None
	if mode == "Header":
		value = (message.get("headers") or {}).get(source)
	else:
		value = (message.get("payload") or {}).get(source)

	return str(value) if value is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_detection`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: detect message type from header, payload, routing key, or a fixed value"
```

---

## Task 5: Consume contract and the fake provider

**Files:**
- Create: `frappe_event_bus/consumer/contract.py`
- Create: `frappe_event_bus/tests/fake_consume_provider.py`
- Test: `frappe_event_bus/tests/test_consumer_worker.py` (append)

**Interfaces:**
- Consumes: `frappe_event_bus.providers.registry.get_provider` (existing).
- Produces: `open_consume_session(consumer) -> ConsumeSession`, raising `NotImplementedError` for any contract other than `per_message`. `ConsumeSession` supports `receive(max_messages)`, `ack(message)`, `reject(message, requeue=False)`, and the context-manager protocol.

- [ ] **Step 1: Write the failing test**

Append to `frappe_event_bus/tests/test_consumer_worker.py`:

```python
from frappe_event_bus.consumer.contract import open_consume_session
from frappe_event_bus.tests.fake_consume_provider import (
	queue_messages,
	register_fake_consume_provider,
	take_acked,
)


class TestConsumeContract(FrappeTestCase):
	def setUp(self):
		register_fake_consume_provider()
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_a_session_receives_and_acknowledges(self):
		consumer = _make_consumer()
		queue_messages([{"payload_raw": '{"a": 1}', "provider_message_id": "m1"}])
		with open_consume_session(consumer) as session:
			messages = session.receive(10)
			self.assertEqual(len(messages), 1)
			session.ack(messages[0])
		self.assertEqual([m["provider_message_id"] for m in take_acked()], ["m1"])

	def test_an_unsupported_contract_is_refused_by_name(self):
		register_fake_consume_provider(contract="batch_commit")
		consumer = _make_consumer()
		with self.assertRaises(NotImplementedError) as ctx:
			open_consume_session(consumer)
		self.assertIn("batch_commit", str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: FAIL — `No module named 'frappe_event_bus.consumer.contract'`

- [ ] **Step 3: Write the contract**

Create `frappe_event_bus/consumer/contract.py`:

```python
"""The consume contract: how the core asks a provider for messages.

Receiving and acknowledging must share one session because broker handles are
connection-scoped — a RabbitMQ delivery tag is only valid on the channel that
delivered it, so acknowledging on a fresh channel is an error. The session is
the unit that owns that lifetime.

Providers declare which contract they implement. Only ``per_message`` exists
today; the dispatch point is here so adding batch-commit later is a branch
rather than a rewrite of the poll loop.
"""

from __future__ import annotations

from typing import Any, Protocol

import frappe

from frappe_event_bus.providers.registry import get_provider

PER_MESSAGE = "per_message"


class ConsumeSession(Protocol):
	"""One connection lifetime. Receive and acknowledge share it."""

	def receive(self, max_messages: int) -> list[dict[str, Any]]: ...

	def ack(self, message: dict[str, Any]) -> None: ...

	def reject(self, message: dict[str, Any], requeue: bool = False) -> None: ...

	def __enter__(self) -> ConsumeSession: ...

	def __exit__(self, *exc_info: Any) -> None: ...


def open_consume_session(consumer: Any) -> ConsumeSession:
	"""Open a consume session for ``consumer``'s provider.

	Raises:
		NotImplementedError: If the provider declares a contract the core does
			not implement yet.
		frappe.ValidationError: If the provider is not registered, or declares
			no consumer factory.
	"""
	spec = get_provider(consumer.provider)
	contract = spec.get("consume_contract", PER_MESSAGE)
	if contract != PER_MESSAGE:
		raise NotImplementedError(
			f"Consume contract {contract!r} is not supported yet. "
			f"Provider {consumer.provider!r} cannot be polled."
		)

	factory_path = spec.get("consumer")
	if not factory_path:
		frappe.throw(
			frappe._("Provider '{0}' does not support consuming.").format(consumer.provider)
		)
	return frappe.get_attr(factory_path)(consumer)
```

- [ ] **Step 4: Write the fake provider**

Create `frappe_event_bus/tests/fake_consume_provider.py`:

```python
"""In-memory consume session used by the consumer tests.

Mirrors ``fake_provider`` on the publishing side: state lives in
``frappe.flags`` so a test can queue messages, then inspect what was
acknowledged or rejected.
"""

from __future__ import annotations

from typing import Any

import frappe


def queue_messages(messages: list[dict[str, Any]]) -> None:
	"""Make ``messages`` available to the next receive call."""
	normalized = []
	for index, message in enumerate(messages):
		normalized.append(
			{
				"provider_message_id": message.get("provider_message_id"),
				"payload_raw": message.get("payload_raw", "{}"),
				"payload": message.get("payload", frappe.parse_json(message.get("payload_raw", "{}"))),
				"headers": message.get("headers", {}),
				"routing_key": message.get("routing_key"),
				"source": message.get("source", "test.queue"),
				"raw_metadata": message.get("raw_metadata", {}),
				"_handle": index,
			}
		)
	frappe.flags.fake_consume_queue = normalized


def take_acked() -> list[dict[str, Any]]:
	"""Return and clear the acknowledged messages."""
	acked = frappe.flags.get("fake_consume_acked") or []
	frappe.flags.fake_consume_acked = []
	return acked


def take_rejected() -> list[dict[str, Any]]:
	"""Return and clear the rejected messages."""
	rejected = frappe.flags.get("fake_consume_rejected") or []
	frappe.flags.fake_consume_rejected = []
	return rejected


class FakeConsumeSession:
	"""Serves queued messages and records acknowledgements."""

	def __init__(self, consumer: Any) -> None:
		self.consumer = consumer

	def receive(self, max_messages: int) -> list[dict[str, Any]]:
		queued = frappe.flags.get("fake_consume_queue") or []
		taken, frappe.flags.fake_consume_queue = queued[:max_messages], queued[max_messages:]
		return taken

	def ack(self, message: dict[str, Any]) -> None:
		frappe.flags.setdefault("fake_consume_acked", []).append(message)

	def reject(self, message: dict[str, Any], requeue: bool = False) -> None:
		frappe.flags.setdefault("fake_consume_rejected", []).append(message)

	def __enter__(self) -> FakeConsumeSession:
		return self

	def __exit__(self, *exc_info: Any) -> None:
		return None


def open_fake_session(consumer: Any) -> FakeConsumeSession:
	"""Provider-side factory referenced by the fake provider spec."""
	return FakeConsumeSession(consumer)


def register_fake_consume_provider(contract: str = "per_message") -> None:
	"""Prime the registry cache with a consuming fake provider."""
	frappe.local._event_bus_provider_cache = {
		"fake": {
			"name": "fake",
			"label": "Fake Provider",
			"connection_doctype": "Event Bus Settings",
			"destination_doctype": "Event Bus Settings",
			"publisher": "frappe_event_bus.tests.fake_provider.FakePublisher",
			"consumer": "frappe_event_bus.tests.fake_consume_provider.open_fake_session",
			"consume_contract": contract,
		}
	}
	frappe.flags.fake_consume_queue = []
	frappe.flags.fake_consume_acked = []
	frappe.flags.fake_consume_rejected = []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: PASS (5 tests — 3 from Task 1, 2 new)

- [ ] **Step 6: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: define the session-scoped consume contract"
```

---

## Task 6: Inbox persistence and duplicate handling

**Files:**
- Create: `frappe_event_bus/consumer/inbox.py`
- Test: `frappe_event_bus/tests/test_inbox.py` (append)

**Interfaces:**
- Consumes: `compute_dedup_key` (Task 3), `detect_message_type` (Task 4).
- Produces: `persist_message(consumer, message) -> Document` returning the inserted Inbox row.

- [ ] **Step 1: Write the failing test**

Append to `frappe_event_bus/tests/test_inbox.py`:

```python
from frappe_event_bus.consumer.inbox import persist_message

CONSUMER_DOC = "_Test EB Persist Consumer"


def _consumer_doc():
	frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER_DOC, force=1)
	return frappe.get_doc(
		{
			"doctype": "Event Bus Consumer",
			"consumer_name": CONSUMER_DOC,
			"provider": "fake",
			"connection": "c",
			"source_type": "RabbitMQ Queue",
			"source": "test.queue",
			"deduplication_strategy": "Payload Field",
			"deduplication_key_expression": "order_id",
			"message_type_detection": "Payload Field",
			"message_type_source": "message_type",
		}
	).insert(ignore_permissions=True)


def _incoming(order_id: str = "SO-1"):
	raw = f'{{"order_id": "{order_id}", "message_type": "OrderCreated"}}'
	return {
		"provider_message_id": "amqp-1",
		"payload_raw": raw,
		"payload": frappe.parse_json(raw),
		"headers": {},
		"routing_key": "order.created",
		"source": "test.queue",
		"raw_metadata": {},
	}


class TestPersistMessage(FrappeTestCase):
	def setUp(self):
		self.consumer = _consumer_doc()

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER_DOC, force=1)

	def test_a_new_message_is_received(self):
		row = persist_message(self.consumer, _incoming())
		self.assertEqual(row.status, "Received")
		self.assertEqual(row.deduplication_key, "SO-1")
		self.assertEqual(row.message_type, "OrderCreated")
		self.assertIsNone(row.duplicate_of)

	def test_a_redelivered_message_is_ignored_and_linked(self):
		"""Redelivery is normal, so it is recorded rather than dropped."""
		original = persist_message(self.consumer, _incoming())
		duplicate = persist_message(self.consumer, _incoming())

		self.assertEqual(duplicate.status, "Ignored")
		self.assertEqual(duplicate.duplicate_of, original.name)
		self.assertEqual(duplicate.duplicate_key, "SO-1")
		self.assertIsNone(duplicate.deduplication_key)
		self.assertEqual(
			frappe.db.get_value("Event Bus Inbox Message", original.name, "status"), "Received"
		)

	def test_a_non_json_payload_is_stored_intact(self):
		"""A malformed body must not fail the batch."""
		message = _incoming()
		message["payload_raw"] = "not json at all"
		message["payload"] = None
		row = persist_message(self.consumer, message)
		self.assertEqual(row.payload, "not json at all")
		self.assertEqual(row.status, "Received")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_inbox`
Expected: FAIL — `No module named 'frappe_event_bus.consumer.inbox'`

- [ ] **Step 3: Write the implementation**

Create `frappe_event_bus/consumer/inbox.py`:

```python
"""Inbox persistence.

Deduplication is enforced by the UNIQUE index on ``deduplication_key``, not by
a lookup before insert. A read-then-write races: two pollers can both find a
key absent and both insert it. With the index, the insert either succeeds or
raises, and the raise is the detection.

Duplicate rows store the key in ``duplicate_key`` and leave the indexed column
NULL, so many duplicates coexist while originals stay unique.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from frappe_event_bus.consumer.dedup import compute_dedup_key
from frappe_event_bus.consumer.detection import detect_message_type


def persist_message(consumer: Any, message: dict[str, Any]) -> Document:
	"""Write ``message`` to the Inbox, as Received or as an Ignored duplicate."""
	dedup_key = compute_dedup_key(consumer, message)
	values = _row_values(consumer, message, dedup_key)

	try:
		return frappe.get_doc(values).insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Redelivery: the broker sent a message we already hold. Recording it
		# keeps the redelivery visible instead of silently swallowing it.
		frappe.db.rollback(save_point="eb_inbox_dedup")
		original = frappe.db.get_value(
			"Event Bus Inbox Message", {"deduplication_key": dedup_key}, "name"
		)
		values.update(
			{
				"status": "Ignored",
				"deduplication_key": None,
				"duplicate_key": dedup_key,
				"duplicate_of": original,
			}
		)
		return frappe.get_doc(values).insert(ignore_permissions=True)


def _row_values(consumer: Any, message: dict[str, Any], dedup_key: str) -> dict[str, Any]:
	"""Build the Inbox row for a freshly received message."""
	return {
		"doctype": "Event Bus Inbox Message",
		"consumer": consumer.name,
		"provider": consumer.provider,
		"source": message.get("source") or consumer.source,
		"external_message_id": message.get("provider_message_id"),
		"message_type": detect_message_type(consumer, message),
		"payload": message.get("payload_raw") or "",
		"headers": json.dumps(message.get("headers") or {}),
		"raw_metadata": json.dumps(message.get("raw_metadata") or {}),
		"status": "Received",
		"deduplication_key": dedup_key,
		"ordering_key": _ordering_key(consumer, message, dedup_key),
		"attempt_count": 0,
		"received_at": now_datetime(),
	}


def _ordering_key(consumer: Any, message: dict[str, Any], dedup_key: str) -> str:
	"""Ordering key, defaulting to the deduplication key.

	Stored but unused in this phase: the processing phase serializes on it.
	"""
	expression = (consumer.ordering_key_expression or "").strip()
	if not expression:
		return dedup_key
	try:
		rendered = frappe.render_template(
			expression,
			{
				"payload": message.get("payload") or {},
				"headers": message.get("headers") or {},
				"consumer": consumer,
			},
		).strip()
	except Exception:
		frappe.log_error(
			title="Event Bus: ordering key expression failed",
			message=frappe.get_traceback(),
		)
		return dedup_key
	return rendered or dedup_key
```

Note the `frappe.db.rollback(save_point="eb_inbox_dedup")` call — the poll loop in Task 8 opens that savepoint before each message, so a failed insert does not poison the transaction for the retry insert.

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_inbox`
Expected: PASS (5 tests — 2 from Task 2, 3 new)

- [ ] **Step 5: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: persist inbound messages, recording redelivery as Ignored"
```

---

## Task 7: Due check, claim, and release

**Files:**
- Create: `frappe_event_bus/consumer/worker.py`
- Test: `frappe_event_bus/tests/test_consumer_worker.py` (append)

**Interfaces:**
- Produces: `is_due(consumer) -> bool`, `claim_consumer(name) -> bool`, `release_consumer(name) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `frappe_event_bus/tests/test_consumer_worker.py`:

```python
from frappe.utils import add_to_date, now_datetime

from frappe_event_bus.consumer import worker as cw


class TestDueAndClaim(FrappeTestCase):
	def setUp(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_a_consumer_that_never_polled_is_due(self):
		consumer = _make_consumer()
		self.assertTrue(cw.is_due(consumer))

	def test_a_recently_polled_consumer_is_not_due(self):
		consumer = _make_consumer(poll_interval=300)
		consumer.db_set("last_polled_at", now_datetime())
		consumer.reload()
		self.assertFalse(cw.is_due(consumer))

	def test_a_consumer_past_its_interval_is_due(self):
		consumer = _make_consumer(poll_interval=60)
		consumer.db_set("last_polled_at", add_to_date(now_datetime(), seconds=-120))
		consumer.reload()
		self.assertTrue(cw.is_due(consumer))

	def test_only_the_first_claimer_wins(self):
		consumer = _make_consumer()
		self.assertTrue(cw.claim_consumer(consumer.name))
		self.assertFalse(cw.claim_consumer(consumer.name))

	def test_releasing_allows_a_later_claim(self):
		consumer = _make_consumer()
		cw.claim_consumer(consumer.name)
		cw.release_consumer(consumer.name)
		self.assertTrue(cw.claim_consumer(consumer.name))

	def test_a_stale_claim_can_be_taken_over(self):
		"""A worker killed mid-cycle must not strand its consumer forever."""
		consumer = _make_consumer(poll_interval=60)
		consumer.db_set("claimed_at", add_to_date(now_datetime(), seconds=-3600))
		self.assertTrue(cw.claim_consumer(consumer.name))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: FAIL — `No module named 'frappe_event_bus.consumer.worker'`

- [ ] **Step 3: Write the implementation**

Create `frappe_event_bus/consumer/worker.py`:

```python
"""The polling worker: decides what to poll, claims it, and drains a batch."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

#: A claim older than this multiple of the poll interval is treated as
#: abandoned, so a worker killed mid-cycle cannot strand its consumer.
STALE_CLAIM_INTERVALS = 3


def is_due(consumer: Any) -> bool:
	"""True when ``consumer`` has waited out its poll interval."""
	if not consumer.last_polled_at:
		return True
	due_at = add_to_date(consumer.last_polled_at, seconds=int(consumer.poll_interval or 60))
	return now_datetime() >= due_at


def claim_consumer(name: str) -> bool:
	"""Atomically claim a consumer for one poll cycle.

	A conditional UPDATE is the claim: only the worker whose UPDATE changes the
	row wins. Without it, a cycle that outruns its interval would be polled
	concurrently and fetch the same backlog twice.
	"""
	consumer = frappe.qb.DocType("Event Bus Consumer")
	now = now_datetime()
	interval = frappe.db.get_value("Event Bus Consumer", name, "poll_interval") or 60
	stale_before = add_to_date(now, seconds=-STALE_CLAIM_INTERVALS * int(interval))

	(
		frappe.qb.update(consumer)
		.set(consumer.claimed_at, now)
		.where(consumer.name == name)
		.where(consumer.claimed_at.isnull() | (consumer.claimed_at < stale_before))
	).run()

	return frappe.db._cursor.rowcount == 1


def release_consumer(name: str) -> None:
	"""Release a claim and stamp the poll time."""
	consumer = frappe.qb.DocType("Event Bus Consumer")
	(
		frappe.qb.update(consumer)
		.set(consumer.claimed_at, None)
		.set(consumer.last_polled_at, now_datetime())
		.where(consumer.name == name)
	).run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: add consumer due-check and claim"
```

---

## Task 8: Poll cycle and dispatcher

**Files:**
- Modify: `frappe_event_bus/consumer/worker.py`
- Modify: `frappe_event_bus/hooks.py` (scheduler_events)
- Test: `frappe_event_bus/tests/test_consumer_worker.py` (append)

**Interfaces:**
- Consumes: `open_consume_session` (Task 5), `persist_message` (Task 6), `is_due`/`claim_consumer`/`release_consumer` (Task 7).
- Produces: `poll_consumer(name) -> dict[str, int]` with keys `received`, `ignored`, `rejected`; `poll_due_consumers() -> dict[str, int]` with keys `polled`, `skipped`.

- [ ] **Step 1: Write the failing test**

Append to `frappe_event_bus/tests/test_consumer_worker.py`:

```python
class TestPollCycle(FrappeTestCase):
	def setUp(self):
		register_fake_consume_provider()
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def tearDown(self):
		frappe.delete_doc_if_exists("Event Bus Consumer", CONSUMER, force=1)

	def test_received_messages_are_persisted_and_acknowledged(self):
		consumer = _make_consumer(enabled=1)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])

		counts = cw.poll_consumer(consumer.name)

		self.assertEqual(counts["received"], 1)
		self.assertEqual([m["provider_message_id"] for m in take_acked()], ["m1"])
		self.assertEqual(
			frappe.db.count("Event Bus Inbox Message", {"consumer": consumer.name}), 1
		)

	def test_an_oversized_message_is_rejected_without_requeue(self):
		"""A poison giant message must not be redelivered forever."""
		consumer = _make_consumer(enabled=1, max_payload_bytes=10)
		queue_messages([{"payload_raw": '{"n": "' + "x" * 500 + '"}', "provider_message_id": "big"}])

		counts = cw.poll_consumer(consumer.name)

		self.assertEqual(counts["rejected"], 1)
		self.assertEqual(counts["received"], 0)
		self.assertEqual([m["provider_message_id"] for m in take_rejected()], ["big"])

	def test_a_redelivered_message_is_ignored_on_the_second_poll(self):
		"""The correctness claim: an unacked-but-stored message stays stored once."""
		consumer = _make_consumer(enabled=1)
		body = '{"n": 7}'
		queue_messages([{"payload_raw": body, "provider_message_id": "m1"}])
		cw.poll_consumer(consumer.name)

		# The broker never saw our ack, so it delivers the same body again.
		queue_messages([{"payload_raw": body, "provider_message_id": "m1"}])
		counts = cw.poll_consumer(consumer.name)

		self.assertEqual(counts["ignored"], 1)
		self.assertEqual(counts["received"], 0)
		rows = frappe.get_all(
			"Event Bus Inbox Message",
			filters={"consumer": consumer.name},
			fields=["status", "duplicate_of"],
			order_by="creation asc",
		)
		self.assertEqual([r.status for r in rows], ["Received", "Ignored"])
		self.assertIsNotNone(rows[1].duplicate_of)

	def test_the_dispatcher_skips_disabled_consumers(self):
		_make_consumer(enabled=0)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])
		cw.poll_due_consumers()
		self.assertEqual(take_acked(), [])

	def test_the_dispatcher_polls_an_enabled_due_consumer(self):
		consumer = _make_consumer(enabled=1)
		queue_messages([{"payload_raw": '{"n": 1}', "provider_message_id": "m1"}])
		counts = cw.poll_due_consumers()
		self.assertEqual(counts["polled"], 1)
		self.assertEqual(
			frappe.db.count("Event Bus Inbox Message", {"consumer": consumer.name}), 1
		)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site dev.localhost run-tests --module frappe_event_bus.tests.test_consumer_worker`
Expected: FAIL — `module 'frappe_event_bus.consumer.worker' has no attribute 'poll_consumer'`

- [ ] **Step 3: Add the poll cycle**

Append to `frappe_event_bus/consumer/worker.py`:

```python
from frappe_event_bus.consumer.contract import open_consume_session
from frappe_event_bus.consumer.inbox import persist_message


def poll_consumer(name: str) -> dict[str, int]:
	"""Drain one batch for ``consumer``.

	Persists and commits every accepted message *before* acknowledging any of
	them. A crash between the two means the broker redelivers a message we
	already hold, which deduplication records as Ignored. There is no ordering
	in which a message is acknowledged but not stored.
	"""
	consumer = frappe.get_doc("Event Bus Consumer", name)
	counts = {"received": 0, "ignored": 0, "rejected": 0}

	with open_consume_session(consumer) as session:
		messages = session.receive(int(consumer.batch_size or 25))
		accepted: list[dict[str, Any]] = []
		rejected: list[dict[str, Any]] = []

		for message in messages:
			if _too_large(consumer, message):
				rejected.append(message)
				continue
			frappe.db.savepoint("eb_inbox_dedup")
			try:
				row = persist_message(consumer, message)
			except Exception:
				frappe.db.rollback(save_point="eb_inbox_dedup")
				frappe.log_error(
					title="Event Bus: inbox persist failed",
					message=frappe.get_traceback(),
				)
				# Left unacknowledged on purpose: the broker will redeliver it.
				continue
			accepted.append(message)
			counts["ignored" if row.status == "Ignored" else "received"] += 1

		frappe.db.commit()

		for message in accepted:
			session.ack(message)
		for message in rejected:
			session.reject(message, requeue=False)
			counts["rejected"] += 1

	return counts


def _too_large(consumer: Any, message: dict[str, Any]) -> bool:
	"""True when the body exceeds the consumer's payload ceiling."""
	limit = int(consumer.max_payload_bytes or 0)
	if limit <= 0:
		return False
	return len((message.get("payload_raw") or "").encode()) > limit


def poll_due_consumers() -> dict[str, int]:
	"""Scheduled entry point: poll every enabled consumer that is due."""
	counts = {"polled": 0, "skipped": 0}
	names = frappe.get_all("Event Bus Consumer", filters={"enabled": 1}, pluck="name")

	for name in names:
		consumer = frappe.get_doc("Event Bus Consumer", name)
		if not is_due(consumer):
			counts["skipped"] += 1
			continue
		if not claim_consumer(name):
			counts["skipped"] += 1
			continue
		try:
			poll_consumer(name)
			counts["polled"] += 1
		except Exception:
			# One unreachable broker must not stop the other consumers.
			frappe.log_error(
				title=f"Event Bus: polling consumer {name} failed",
				message=frappe.get_traceback(),
			)
		finally:
			release_consumer(name)

	frappe.db.commit()
	return counts
```

- [ ] **Step 4: Register the scheduled job**

In `frappe_event_bus/hooks.py`, add the consumer dispatcher to `scheduler_events`, keeping the existing entries:

```python
scheduler_events = {
	"daily": [
		"frappe_event_bus.publisher.retention.purge_outbox",
	],
	"cron": {
		"*/5 * * * *": [
			"frappe_event_bus.publisher.retry.process_outbox",
		],
		# Consumers carry their own poll_interval; this runs every minute and
		# polls only those that are due.
		"* * * * *": [
			"frappe_event_bus.consumer.worker.poll_due_consumers",
		],
	},
}
```

- [ ] **Step 5: Run the full suite**

Run: `bench --site dev.localhost run-tests --app frappe_event_bus`
Expected: PASS — 83 existing plus 16 new from Tasks 1-8.

- [ ] **Step 6: Commit**

```bash
ruff format . && git add -A
git commit -m "feat: poll due consumers and drain batches into the inbox"
```

---

## Task 9: Documentation

**Files:**
- Create: `docs/concepts/consumers.md`
- Modify: `docs/index.md`
- Modify: `RELEASE_NOTES.md`

**Interfaces:**
- Consumes: everything above. No code.

- [ ] **Step 1: Write the concept page**

Create `docs/concepts/consumers.md` covering: what a consumer is; the persist-commit-acknowledge ordering and why redelivery is normal; the five deduplication strategies with Payload Hash as the default; that scope is global and `{{ consumer.name }}-...` is the escape hatch; the four message-type detection modes; poll interval and the one-minute dispatcher; that consumers ship disabled; and that Phase A only ever sets `Received` and `Ignored`.

State plainly that messages are persisted and nothing acts on them yet — handlers arrive in the processing phase.

- [ ] **Step 2: Link it from the docs index**

In `docs/index.md`, add to the Concepts table:

```markdown
| [Consumers](concepts/consumers.md) | Receiving messages from a broker into the Inbox. |
```

- [ ] **Step 3: Add a release note**

In `RELEASE_NOTES.md`, under `## [Unreleased]`, replace `Nothing yet.` with an `### Added` section describing consumer ingestion, and state the limitation: messages are persisted but not yet processed.

- [ ] **Step 4: Verify links resolve**

Run the relative-link check used previously over `docs/` and `RELEASE_NOTES.md`.
Expected: 0 broken links.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: document consumer ingestion"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §2 persist-commit-ack ordering | 8 (`poll_consumer`, and its redelivery test) |
| §3 session contract + dispatch | 5 |
| §4 dedup scope, unique index, strategies | 2 (index), 3 (strategies), 6 (duplicate handling) |
| §5 Consumer doctype | 1 |
| §5 Inbox doctype, all seven statuses | 2 |
| §6 dispatcher, claiming, poll cycle | 7, 8 |
| §6 failure isolation, oversized messages | 8 |
| §7 disabled by default | 1 |
| §8 testing, incl. the redelivery test | 3, 4, 6, 7, 8 |
| §9 out of scope | not implemented, by design |

The RabbitMQ consume session (spec §3, "RabbitMQ implementation") is **not** in this plan — it lives in the provider repo and needs its own plan. Phase A is testable without it via the fake provider; the live-broker work is the natural follow-up.

**Placeholders:** none. Every step carries the code it needs.

**Type consistency:** `compute_dedup_key`, `detect_message_type`, `persist_message`, `open_consume_session`, `is_due`, `claim_consumer`, `release_consumer`, `poll_consumer`, `poll_due_consumers` are used in later tasks exactly as defined. The message dict keys (`payload_raw`, `payload`, `headers`, `routing_key`, `provider_message_id`, `source`, `raw_metadata`, `_handle`) are consistent across the fake provider, dedup, detection, and inbox.
