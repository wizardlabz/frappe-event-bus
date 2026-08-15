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
