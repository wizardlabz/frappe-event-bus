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

	try:
		(
			frappe.qb.update(consumer)
			.set(consumer.claimed_at, now)
			.where(consumer.name == name)
			.where(consumer.claimed_at.isnull() | (consumer.claimed_at < stale_before))
		).run()
	except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
		# Another worker holds the row lock and InnoDB picked us as the victim.
		# Losing the race is the same outcome as losing it cleanly: skip the
		# consumer and let the winner poll it.
		return False

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
			# Distinct name from persist_message's own savepoint, which nests
			# inside this one.
			frappe.db.savepoint("eb_inbox_msg")
			try:
				row = persist_message(consumer, message)
			except Exception:
				frappe.db.rollback(save_point="eb_inbox_msg")
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
